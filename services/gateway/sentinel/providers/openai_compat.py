"""Adapter for any OpenAI-compatible /chat/completions endpoint.

Covers DeepSeek, OpenAI, Groq, Together, OpenRouter, vLLM and Ollama, which all
speak the same wire format. Streaming is consumed as SSE and normalised into the
gateway's `Chunk` stream so downstream accounting never branches per provider.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..models import ModelEntry
from ..settings import settings
from .base import ChatCall, Chunk, UpstreamError

log = logging.getLogger("sentinel.providers")

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 522, 524}


class OpenAICompatProvider:
    """One instance per upstream, holding a pooled HTTP client."""

    live = True

    def __init__(self, name: str, base_url: str, api_key: str, label: str = "") -> None:
        self.name = name
        self.label = label or name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(
                    settings.upstream_timeout_seconds,
                    connect=settings.upstream_connect_timeout_seconds,
                ),
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
                headers={
                    "authorization": f"Bearer {self._api_key}",
                    "content-type": "application/json",
                    "accept": "text/event-stream",
                    "user-agent": f"sentinel-gateway/{settings.app_version}",
                },
            )
        return self._client

    def _payload(self, call: ChatCall, model: ModelEntry) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model.upstream_model,
            "messages": call.messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if call.temperature is not None:
            body["temperature"] = call.temperature
        if call.max_tokens:
            body["max_tokens"] = min(call.max_tokens, model.max_output_tokens)
        if call.top_p is not None:
            body["top_p"] = call.top_p
        if call.stop:
            body["stop"] = call.stop
        if call.presence_penalty is not None:
            body["presence_penalty"] = call.presence_penalty
        if call.frequency_penalty is not None:
            body["frequency_penalty"] = call.frequency_penalty
        if call.response_format:
            body["response_format"] = call.response_format
        return body

    async def stream(self, call: ChatCall, model: ModelEntry) -> AsyncIterator[Chunk]:
        payload = self._payload(call, model)
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        cached_prompt_tokens = 0
        finish_reason: str | None = None

        try:
            async with self._http().stream("POST", "/chat/completions", json=payload) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode(errors="replace")[:600]
                    raise UpstreamError(
                        f"{self.name} returned {response.status_code}: {body}",
                        status_code=response.status_code,
                        retryable=response.status_code in RETRYABLE_STATUS,
                        provider=self.name,
                    )

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    usage = event.get("usage")
                    if isinstance(usage, dict):
                        prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
                        completion_tokens = usage.get("completion_tokens", completion_tokens)
                        # DeepSeek/OpenAI report prompt-cache hits, which are
                        # billed at a fraction of the input rate.
                        details = usage.get("prompt_tokens_details") or {}
                        cached_prompt_tokens = int(
                            details.get("cached_tokens")
                            or usage.get("prompt_cache_hit_tokens")
                            or cached_prompt_tokens
                        )

                    for choice in event.get("choices") or []:
                        delta = choice.get("delta") or {}
                        text = delta.get("content") or ""
                        reasoning = delta.get("reasoning_content") or ""
                        if text or reasoning:
                            yield Chunk(delta=text, reasoning_delta=reasoning)
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
        except UpstreamError:
            raise
        except httpx.TimeoutException as exc:
            raise UpstreamError(
                f"{self.name} timed out after {settings.upstream_timeout_seconds}s",
                status_code=504,
                retryable=True,
                provider=self.name,
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamError(
                f"{self.name} transport error: {exc}",
                retryable=True,
                provider=self.name,
            ) from exc

        yield Chunk(
            finish_reason=finish_reason or "stop",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_prompt_tokens=cached_prompt_tokens,
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
