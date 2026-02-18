"""LLM client abstraction supporting Ollama (local) and DeepInfra (cloud).

Provides a unified interface for conversation and vision LLM calls.
The active backend is selected by LLM_PROVIDER in config. Both backends
disable Qwen3's thinking mode (on by default) via provider-specific flags.
"""

from __future__ import annotations

import abc
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


# ─── Base ABC ──────────────────────────────────────────────────────────


class BaseLLMClient(abc.ABC):
    """Abstract interface that all LLM backends must implement."""

    # ── shared helpers (concrete) ───────────────────────────────────

    def _resolve_model(self, model: str | None, *, vision: bool = False) -> str:
        if model is not None:
            return model
        return settings.llm.vision_model if vision else settings.llm.conversation_model

    def _resolve_max_tokens(self, max_tokens: int | None, model: str) -> int:
        if max_tokens is not None:
            return max_tokens
        if model == settings.llm.vision_model:
            return settings.llm.ocr_max_tokens
        return settings.llm.conversation_max_tokens

    def _resolve_timeout(self, model: str) -> float:
        if model == settings.llm.vision_model:
            return float(settings.llm.ocr_timeout)
        return float(settings.llm.conversation_timeout)

    # ── abstract methods ────────────────────────────────────────────

    @abc.abstractmethod
    async def ensure_model(self, model_name: str) -> None:
        """Ensure the model is ready to serve requests."""

    @abc.abstractmethod
    async def chat(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str: ...

    @abc.abstractmethod
    async def chat_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[str, None]: ...

    @abc.abstractmethod
    async def chat_vision(
        self,
        system_prompt: str,
        text_prompt: str,
        image_base64: str,
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> str: ...

    @abc.abstractmethod
    async def close(self) -> None: ...


# ─── DeepInfra (OpenAI-compatible cloud) ───────────────────────────────


class DeepInfraClient(BaseLLMClient):
    """Async client for DeepInfra's OpenAI-compatible /chat/completions endpoint.

    Uses ``chat_template_kwargs.enable_thinking = false`` to disable
    Qwen3's chain-of-thought reasoning on DeepInfra.
    """

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.llm.deepinfra_base_url,
            headers={"Authorization": f"Bearer {settings.llm.deepinfra_api_key}"},
            timeout=httpx.Timeout(90.0, connect=10.0),
        )

    async def ensure_model(self, model_name: str) -> None:
        """No-op — cloud provider manages model availability."""

    async def chat(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        model = self._resolve_model(model)
        max_tokens = self._resolve_max_tokens(max_tokens, model)
        timeout = self._resolve_timeout(model)

        api_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *messages,
        ]

        prompt_hash = hashlib.md5(system_prompt.encode()).hexdigest()[:8]
        await emit(SystemEvent(
            event_type=EventType.LLM_REQUEST,
            data={"model": model, "prompt_hash": prompt_hash, "message_count": len(messages)},
            source_module="llm.client",
        ))

        start = time.monotonic()
        try:
            response = await self._client.post(
                "/chat/completions",
                json={
                    "model": model,
                    "messages": api_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": False,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
                timeout=timeout,
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            elapsed_ms = int((time.monotonic() - start) * 1000)

            content: str = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)

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
                model, elapsed_ms, completion_tokens,
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
        model = self._resolve_model(model)
        max_tokens = self._resolve_max_tokens(max_tokens, model)
        timeout = self._resolve_timeout(model)

        api_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *messages,
        ]

        prompt_hash = hashlib.md5(system_prompt.encode()).hexdigest()[:8]
        await emit(SystemEvent(
            event_type=EventType.LLM_REQUEST,
            data={"model": model, "prompt_hash": prompt_hash, "message_count": len(messages), "streaming": True},
            source_module="llm.client",
        ))

        start = time.monotonic()
        full_content = ""
        try:
            async with self._client.stream(
                "POST",
                "/chat/completions",
                json={
                    "model": model,
                    "messages": api_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": True,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
                timeout=timeout,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    # SSE format: "data: {json}" or "data: [DONE]"
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]  # strip "data: " prefix
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        token = delta.get("content", "")
                        if token:
                            full_content += token
                            yield token
                    except (json.JSONDecodeError, IndexError):
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
                model, elapsed_ms, len(full_content),
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
        model = self._resolve_model(model, vision=True)
        max_tokens = self._resolve_max_tokens(max_tokens, model)
        timeout = self._resolve_timeout(model)

        # OpenAI vision format: content is a list of text + image_url blocks
        api_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text_prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
                    },
                ],
            },
        ]

        prompt_hash = hashlib.md5(text_prompt.encode()).hexdigest()[:8]
        await emit(SystemEvent(
            event_type=EventType.LLM_REQUEST,
            data={"model": model, "prompt_hash": prompt_hash, "vision": True},
            source_module="llm.client",
        ))

        start = time.monotonic()
        try:
            response = await self._client.post(
                "/chat/completions",
                json={
                    "model": model,
                    "messages": api_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": False,
                },
                timeout=timeout,
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            elapsed_ms = int((time.monotonic() - start) * 1000)

            content: str = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)

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
                model, elapsed_ms, completion_tokens,
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
        await self._client.aclose()


# ─── Ollama (local) ───────────────────────────────────────────────────


class OllamaClient(BaseLLMClient):
    """Async client for Ollama's native /api/chat endpoint.

    On 16GB M2: only one model fits in memory at a time. The client
    tracks which model is loaded and handles swapping via keep_alive.
    Uses think=false to disable Qwen3's chain-of-thought reasoning.
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
                timeout=120.0,
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
        model = self._resolve_model(model)
        max_tokens = self._resolve_max_tokens(max_tokens, model)
        timeout = self._resolve_timeout(model)
        await self.ensure_model(model)

        api_messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            *messages,
        ]

        prompt_hash = hashlib.md5(system_prompt.encode()).hexdigest()[:8]
        await emit(SystemEvent(
            event_type=EventType.LLM_REQUEST,
            data={"model": model, "prompt_hash": prompt_hash, "message_count": len(messages)},
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
                timeout=timeout,
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
                model, elapsed_ms, completion_tokens,
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
        model = self._resolve_model(model)
        max_tokens = self._resolve_max_tokens(max_tokens, model)
        timeout = self._resolve_timeout(model)
        await self.ensure_model(model)

        api_messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            *messages,
        ]

        prompt_hash = hashlib.md5(system_prompt.encode()).hexdigest()[:8]
        await emit(SystemEvent(
            event_type=EventType.LLM_REQUEST,
            data={"model": model, "prompt_hash": prompt_hash, "message_count": len(messages), "streaming": True},
            source_module="llm.client",
        ))

        start = time.monotonic()
        full_content = ""
        try:
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
                timeout=timeout,
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
                model, elapsed_ms, len(full_content),
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
        model = self._resolve_model(model, vision=True)
        max_tokens = self._resolve_max_tokens(max_tokens, model)
        timeout = self._resolve_timeout(model)
        await self.ensure_model(model)

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
            data={"model": model, "prompt_hash": prompt_hash, "vision": True},
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
                timeout=timeout,
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
                model, elapsed_ms, completion_tokens,
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
        await self._client.aclose()


# ─── Factory + singleton ──────────────────────────────────────────────


def _create_llm_client() -> BaseLLMClient:
    """Create the LLM client based on the configured provider."""
    provider = settings.llm.llm_provider.lower()
    if provider == "deepinfra":
        return DeepInfraClient()
    if provider == "ollama":
        return OllamaClient()
    msg = f"Unknown LLM provider: {provider!r}. Use 'deepinfra' or 'ollama'."
    raise ValueError(msg)


llm_client: BaseLLMClient = _create_llm_client()
