"""Upstream adapters and the provider registry."""

from __future__ import annotations

import logging

from ..settings import settings
from .base import ChatCall, ChatResult, Chunk, Provider, UpstreamError
from .openai_compat import OpenAICompatProvider
from .simulated import SimulatedProvider

log = logging.getLogger("sentinel.providers")

_registry: dict[str, Provider] = {}


def build_registry() -> dict[str, Provider]:
    providers: dict[str, Provider] = {"simulated": SimulatedProvider()}

    if settings.simulate_only:
        log.info("SIMULATE_ONLY is set — live upstreams disabled")
        return providers

    if settings.deepseek_api_key:
        providers["deepseek"] = OpenAICompatProvider(
            "deepseek", settings.deepseek_base_url, settings.deepseek_api_key, "DeepSeek"
        )
    if settings.openai_api_key:
        providers["openai"] = OpenAICompatProvider(
            "openai", settings.openai_base_url, settings.openai_api_key, "OpenAI"
        )
    if settings.compat_api_key and settings.compat_base_url:
        providers["compat"] = OpenAICompatProvider(
            "compat", settings.compat_base_url, settings.compat_api_key, settings.compat_label
        )
    return providers


def registry() -> dict[str, Provider]:
    global _registry
    if not _registry:
        _registry = build_registry()
        log.info("providers ready: %s", ", ".join(sorted(_registry)))
    return _registry


def get(name: str) -> Provider | None:
    return registry().get(name)


def available(name: str) -> bool:
    return name in registry()


async def close_all() -> None:
    for provider in list(_registry.values()):
        await provider.close()
    _registry.clear()


__all__ = [
    "ChatCall",
    "ChatResult",
    "Chunk",
    "Provider",
    "UpstreamError",
    "available",
    "close_all",
    "get",
    "registry",
]
