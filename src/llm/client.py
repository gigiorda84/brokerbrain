"""Ollama LLM client with model-swapping for 16GB RAM constraint.

Wraps Ollama's OpenAI-compatible API. Tracks the currently loaded model
and handles swapping between conversation (Qwen3 8B) and vision (Qwen2.5-VL 7B).
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

import httpx

from src.admin.events import emit
from src.config import settings
from src.schemas.events import EventType, SystemEvent

logger = logging.getLogger(__name__)


class OllamaClient:
    """Async client for Ollama's OpenAI-compatible chat API.

    On 16GB M2: only one model fits in memory at a time. The client
    tracks which model is loaded and handles swapping via keep_alive.
    """

    def __init__(self) -> None:
        self._base_url = settings.llm.ollama_base_url
        self._current_model: str | None = None
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(90.0, connect=10.0),
        )

    async def ensure_model(self, model_name: str) -> None:
        """Ensure the specified model is loaded in Ollama.

        If a different model is currently loaded, unload it first
        by setting keep_alive=0, then load the new one.
        """
        if self._current_model == model_name:
            return

        # Unload current model if one is loaded
        if self._current_model is not None:
            logger.info("Unloading model %s", self._current_model)
            try:
                await self._client.post(
                    "/api/generate",
                    json={"model": self._current_model, "keep_alive": 0},
                )
            except httpx.HTTPError:
                logger.warning("Failed to unload model %s", self._current_model)

            await emit(SystemEvent(
                event_type=EventType.LLM_MODEL_SWAP,
                data={"from": self._current_model, "to": model_name},
                source_module="llm.client",
            ))

        # Load new model (warm it up with empty generate)
        logger.info("Loading model %s", model_name)
        try:
            await self._client.post(
                "/api/generate",
                json={
                    "model": model_name,
                    "prompt": "",
                    "keep_alive": settings.llm.keep_alive,
                },
                timeout=120.0,  # Model loading can take time
            )
            self._current_model = model_name
            logger.info("Model %s loaded", model_name)
        except httpx.HTTPError:
            logger.exception("Failed to load model %s", model_name)
            raise

    async def chat(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        """Send a chat completion request to Ollama.

        Args:
            system_prompt: System-level instructions for the LLM.
            messages: List of {"role": "user"|"assistant", "content": "..."}.
            model: Model name override. Defaults to conversation model.
            temperature: Sampling temperature.
            max_tokens: Max response tokens.

        Returns:
            The LLM's text response.
        """
        model = model or settings.llm.conversation_model
        await self.ensure_model(model)

        timeout = (
            settings.llm.ocr_timeout
            if model == settings.llm.vision_model
            else settings.llm.conversation_timeout
        )

        # Build messages array with system prompt
        api_messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            *messages,
        ]

        prompt_hash = hashlib.md5(system_prompt.encode()).hexdigest()[:8]

        await emit(SystemEvent(
            event_type=EventType.LLM_REQUEST,
            data={
                "model": model,
                "prompt_hash": prompt_hash,
                "message_count": len(messages),
            },
            source_module="llm.client",
        ))

        start = time.monotonic()
        try:
            response = await self._client.post(
                "/v1/chat/completions",
                json={
                    "model": model,
                    "messages": api_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": False,
                },
                timeout=float(timeout),
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            elapsed_ms = int((time.monotonic() - start) * 1000)

            content: str = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})

            await emit(SystemEvent(
                event_type=EventType.LLM_RESPONSE,
                data={
                    "model": model,
                    "latency_ms": elapsed_ms,
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                },
                source_module="llm.client",
            ))

            logger.info(
                "LLM response: model=%s latency=%dms tokens=%d",
                model,
                elapsed_ms,
                usage.get("completion_tokens", 0),
            )
            return content

        except httpx.TimeoutException:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            await emit(SystemEvent(
                event_type=EventType.LLM_ERROR,
                data={"model": model, "error": "timeout", "latency_ms": elapsed_ms},
                source_module="llm.client",
            ))
            logger.error("LLM timeout after %dms for model %s", elapsed_ms, model)
            raise

        except httpx.HTTPError as exc:
            await emit(SystemEvent(
                event_type=EventType.LLM_ERROR,
                data={"model": model, "error": str(exc)},
                source_module="llm.client",
            ))
            logger.exception("LLM HTTP error for model %s", model)
            raise

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()


# Module-level singleton
llm_client = OllamaClient()
