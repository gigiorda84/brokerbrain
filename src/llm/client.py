"""Ollama LLM client with model-swapping for 16GB RAM constraint.

Uses Ollama's native /api/chat endpoint (not OpenAI-compat) so we can
disable Qwen3's thinking mode via think=false. Tracks the currently loaded
model and handles swapping between conversation and vision models.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from src.admin.events import emit
from src.config import settings
from src.schemas.events import EventType, SystemEvent

logger = logging.getLogger(__name__)


class OllamaClient:
    """Async client for Ollama's native /api/chat endpoint.

    On 16GB M2: only one model fits in memory at a time. The client
    tracks which model is loaded and handles swapping via keep_alive.
    Uses think=false to disable Qwen3's chain-of-thought reasoning,
    which wastes tokens and dramatically slows responses.
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
        max_tokens: int | None = None,
    ) -> str:
        """Send a chat request to Ollama's native API (non-streaming, no thinking).

        Args:
            system_prompt: System-level instructions for the LLM.
            messages: List of {"role": "user"|"assistant", "content": "..."}.
            model: Model name override. Defaults to conversation model.
            temperature: Sampling temperature.
            max_tokens: Max response tokens. Defaults to config value.

        Returns:
            The LLM's text response.
        """
        model = model or settings.llm.conversation_model
        if max_tokens is None:
            max_tokens = (
                settings.llm.ocr_max_tokens
                if model == settings.llm.vision_model
                else settings.llm.conversation_max_tokens
            )
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
                "/api/chat",
                json={
                    "model": model,
                    "messages": api_messages,
                    "stream": False,
                    "think": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens,
                    },
                },
                timeout=float(timeout),
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            elapsed_ms = int((time.monotonic() - start) * 1000)

            content: str = data["message"]["content"]
            prompt_tokens = data.get("prompt_eval_count", 0)
            completion_tokens = data.get("eval_count", 0)

            await emit(SystemEvent(
                event_type=EventType.LLM_RESPONSE,
                data={
                    "model": model,
                    "latency_ms": elapsed_ms,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                },
                source_module="llm.client",
            ))

            logger.info(
                "LLM response: model=%s latency=%dms tokens=%d",
                model,
                elapsed_ms,
                completion_tokens,
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

    async def chat_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[str, None]:
        """Send a streaming chat request to Ollama's native API (no thinking).

        Yields text chunks as they arrive. Uses /api/chat with stream=true
        and think=false to disable Qwen3's chain-of-thought reasoning.

        Args:
            system_prompt: System-level instructions for the LLM.
            messages: List of {"role": "user"|"assistant", "content": "..."}.
            model: Model name override. Defaults to conversation model.
            temperature: Sampling temperature.
            max_tokens: Max response tokens. Defaults to config value.

        Yields:
            Text chunks as they are generated.
        """
        model = model or settings.llm.conversation_model
        if max_tokens is None:
            max_tokens = (
                settings.llm.ocr_max_tokens
                if model == settings.llm.vision_model
                else settings.llm.conversation_max_tokens
            )
        await self.ensure_model(model)

        timeout = (
            settings.llm.ocr_timeout
            if model == settings.llm.vision_model
            else settings.llm.conversation_timeout
        )

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
                "streaming": True,
            },
            source_module="llm.client",
        ))

        start = time.monotonic()
        full_content = ""
        try:
            # Ollama /api/chat streams newline-delimited JSON (not SSE)
            async with self._client.stream(
                "POST",
                "/api/chat",
                json={
                    "model": model,
                    "messages": api_messages,
                    "stream": True,
                    "think": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens,
                    },
                },
                timeout=float(timeout),
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                        if chunk.get("done"):
                            break
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            full_content += token
                            yield token
                    except json.JSONDecodeError:
                        continue

            elapsed_ms = int((time.monotonic() - start) * 1000)
            await emit(SystemEvent(
                event_type=EventType.LLM_RESPONSE,
                data={
                    "model": model,
                    "latency_ms": elapsed_ms,
                    "streaming": True,
                    "total_chars": len(full_content),
                },
                source_module="llm.client",
            ))
            logger.info(
                "LLM stream complete: model=%s latency=%dms chars=%d",
                model,
                elapsed_ms,
                len(full_content),
            )

        except httpx.TimeoutException:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            await emit(SystemEvent(
                event_type=EventType.LLM_ERROR,
                data={"model": model, "error": "timeout", "latency_ms": elapsed_ms, "streaming": True},
                source_module="llm.client",
            ))
            logger.error("LLM stream timeout after %dms for model %s", elapsed_ms, model)
            raise

        except httpx.HTTPError as exc:
            await emit(SystemEvent(
                event_type=EventType.LLM_ERROR,
                data={"model": model, "error": str(exc), "streaming": True},
                source_module="llm.client",
            ))
            logger.exception("LLM stream HTTP error for model %s", model)
            raise

    async def chat_vision(
        self,
        system_prompt: str,
        text_prompt: str,
        image_base64: str,
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> str:
        """Send a vision chat request with an image to Ollama's native API.

        Args:
            system_prompt: System-level instructions for the VLM.
            text_prompt: User text prompt to accompany the image.
            image_base64: Base64-encoded image data.
            model: Model name override. Defaults to vision model.
            temperature: Sampling temperature (low for OCR).
            max_tokens: Max response tokens. Defaults to config value.

        Returns:
            The VLM's text response.
        """
        model = model or settings.llm.vision_model
        if max_tokens is None:
            max_tokens = settings.llm.ocr_max_tokens
        await self.ensure_model(model)

        timeout = settings.llm.ocr_timeout

        # Ollama native API uses "images" field on the user message
        api_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": text_prompt,
                "images": [image_base64],
            },
        ]

        prompt_hash = hashlib.md5(text_prompt.encode()).hexdigest()[:8]

        await emit(SystemEvent(
            event_type=EventType.LLM_REQUEST,
            data={
                "model": model,
                "prompt_hash": prompt_hash,
                "vision": True,
            },
            source_module="llm.client",
        ))

        start = time.monotonic()
        try:
            response = await self._client.post(
                "/api/chat",
                json={
                    "model": model,
                    "messages": api_messages,
                    "stream": False,
                    "think": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens,
                    },
                },
                timeout=float(timeout),
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            elapsed_ms = int((time.monotonic() - start) * 1000)

            content: str = data["message"]["content"]
            prompt_tokens = data.get("prompt_eval_count", 0)
            completion_tokens = data.get("eval_count", 0)

            await emit(SystemEvent(
                event_type=EventType.LLM_RESPONSE,
                data={
                    "model": model,
                    "latency_ms": elapsed_ms,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "vision": True,
                },
                source_module="llm.client",
            ))

            logger.info(
                "VLM response: model=%s latency=%dms tokens=%d",
                model,
                elapsed_ms,
                completion_tokens,
            )
            return content

        except httpx.TimeoutException:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            await emit(SystemEvent(
                event_type=EventType.LLM_ERROR,
                data={"model": model, "error": "timeout", "latency_ms": elapsed_ms, "vision": True},
                source_module="llm.client",
            ))
            logger.error("VLM timeout after %dms for model %s", elapsed_ms, model)
            raise

        except httpx.HTTPError as exc:
            await emit(SystemEvent(
                event_type=EventType.LLM_ERROR,
                data={"model": model, "error": str(exc), "vision": True},
                source_module="llm.client",
            ))
            logger.exception("VLM HTTP error for model %s", model)
            raise

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()


# Module-level singleton
llm_client = OllamaClient()
