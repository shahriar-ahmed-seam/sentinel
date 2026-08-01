"""Provider contract shared by every upstream adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..models import ModelEntry


class UpstreamError(RuntimeError):
    """Failure talking to an upstream. `retryable` drives the retry policy."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        provider: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.provider = provider


@dataclass
class ChatCall:
    """Normalised inbound request, provider-agnostic."""

    messages: list[dict[str, Any]]
    temperature: float = 0.7
    max_tokens: int | None = None
    top_p: float | None = None
    stop: list[str] | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    response_format: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def prompt_text(self) -> str:
        parts: list[str] = []
        for message in self.messages:
            content = message.get("content")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                parts.extend(
                    block["text"]
                    for block in content
                    if isinstance(block, dict) and isinstance(block.get("text"), str)
                )
        return "\n".join(parts)


@dataclass
class Chunk:
    """One streamed increment."""

    delta: str = ""
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cached_prompt_tokens: int = 0
    reasoning_delta: str = ""


@dataclass
class ChatResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str = "stop"
    cached_prompt_tokens: int = 0
    reasoning: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class Provider(Protocol):
    name: str
    live: bool

    async def stream(self, call: ChatCall, model: ModelEntry) -> AsyncIterator[Chunk]: ...

    async def close(self) -> None: ...
