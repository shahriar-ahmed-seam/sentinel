"""Exact-match response cache.

Keyed on a canonical hash of the messages plus the parameters that change the
answer (model scope, temperature, max_tokens, response format). Only
deterministic-ish calls are cached by default — caching a temperature-0.9
brainstorm would be wrong — but a caller can opt in per request.

A cache hit costs nothing, so the avoided spend is recorded against the entry
and rolled up into the platform's savings figure.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import CacheEntry, utcnow
from .observability import cache_ops, savings
from .settings import settings

log = logging.getLogger("sentinel.cache")
_WHITESPACE = re.compile(r"\s+")


def _normalise(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def cache_key(
    *,
    messages: list[dict[str, Any]],
    scope: str,
    temperature: float,
    max_tokens: int | None,
    response_format: dict[str, Any] | None = None,
) -> str:
    canonical = {
        "scope": scope,
        "temperature": round(float(temperature or 0.0), 3),
        "max_tokens": max_tokens or 0,
        "format": response_format or {},
        "messages": [
            {
                "role": message.get("role", "user"),
                "content": _normalise(message["content"])
                if isinstance(message.get("content"), str)
                else message.get("content"),
            }
            for message in messages
        ],
    }
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def eligible(temperature: float, requested: bool | None) -> tuple[bool, str]:
    from .runtime import config

    if not config.cache_enabled:
        return False, "cache disabled"
    if requested is False:
        return False, "caller opted out"
    if requested:
        return True, "caller opted in"
    if temperature is not None and temperature > config.cache_max_temperature:
        return False, f"temperature {temperature} above the cacheable ceiling"
    return True, "deterministic parameters"


async def lookup(session: AsyncSession, key: str) -> CacheEntry | None:
    entry = await session.scalar(select(CacheEntry).where(CacheEntry.cache_key == key))
    if entry is None:
        cache_ops.labels("miss").inc()
        return None
    if entry.expires_at and entry.expires_at <= utcnow():
        await session.delete(entry)
        cache_ops.labels("expired").inc()
        return None
    entry.hits += 1
    entry.last_hit_at = utcnow()
    entry.saved_usd = round(entry.saved_usd + entry.origin_cost_usd, 8)
    cache_ops.labels("hit").inc()
    savings.labels("cache").inc(entry.origin_cost_usd)
    return entry


async def store(
    session: AsyncSession,
    *,
    key: str,
    model_slug: str,
    provider: str,
    completion: str,
    response: dict[str, Any],
    prompt_tokens: int,
    completion_tokens: int,
    origin_cost_usd: float,
) -> None:
    from .runtime import config

    existing = await session.scalar(select(CacheEntry).where(CacheEntry.cache_key == key))
    if existing is not None:
        return
    session.add(
        CacheEntry(
            cache_key=key,
            model_slug=model_slug,
            provider=provider,
            completion=completion,
            response=response,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            origin_cost_usd=origin_cost_usd,
            expires_at=utcnow() + timedelta(seconds=config.cache_ttl_seconds),
        )
    )
    cache_ops.labels("store").inc()


async def stats(session: AsyncSession) -> dict[str, Any]:
    row = (
        await session.execute(
            select(
                func.count(CacheEntry.id),
                func.coalesce(func.sum(CacheEntry.hits), 0),
                func.coalesce(func.sum(CacheEntry.saved_usd), 0.0),
                func.coalesce(func.sum(CacheEntry.completion_tokens), 0),
            )
        )
    ).one()
    entries, hits, saved, cached_tokens = row
    from .runtime import config

    return {
        "entries": int(entries or 0),
        "hits": int(hits or 0),
        "saved_usd": round(float(saved or 0.0), 6),
        "cached_completion_tokens": int(cached_tokens or 0),
        "ttl_seconds": config.cache_ttl_seconds,
        "max_entries": settings.cache_max_entries,
        "enabled": config.cache_enabled,
        "max_temperature": config.cache_max_temperature,
    }


async def purge(session: AsyncSession, *, expired_only: bool = False) -> int:
    statement = delete(CacheEntry)
    if expired_only:
        statement = statement.where(CacheEntry.expires_at <= utcnow())
    result = await session.execute(statement)
    return int(result.rowcount or 0)


async def evict_overflow(session: AsyncSession) -> int:
    """Trim the least recently useful entries when over the configured ceiling."""
    total = int(await session.scalar(select(func.count(CacheEntry.id))) or 0)
    overflow = total - settings.cache_max_entries
    if overflow <= 0:
        return 0
    victims = (
        (
            await session.execute(
                select(CacheEntry.id)
                .order_by(CacheEntry.hits.asc(), CacheEntry.created_at.asc())
                .limit(overflow)
            )
        )
        .scalars()
        .all()
    )
    if not victims:
        return 0
    await session.execute(delete(CacheEntry).where(CacheEntry.id.in_(victims)))
    cache_ops.labels("evicted").inc(len(victims))
    return len(victims)
