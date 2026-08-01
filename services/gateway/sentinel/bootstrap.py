"""First-boot seeding: catalogue, policies, a demo key and a little traffic."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from sqlalchemy import func, select

from . import providers
from .db import session_scope
from .gateway import RequestContext, gateway
from .models import ApiKey, ModelEntry, RoutingPolicy, utcnow
from .policy import seed_policies
from .pricing import seed_catalogue
from .security import mint_api_key
from .settings import settings

log = logging.getLogger("sentinel.bootstrap")

WARMUP_PROMPTS = [
    ("hey", None),
    ("What does a circuit breaker protect against?", None),
    (
        "Explain step by step how to choose between a read replica and a cache for a "
        "read-heavy endpoint, and analyse the failure modes of each.",
        None,
    ),
    ("Summarise the difference between a rate limit and a quota.", "latency-first"),
    ("What does a circuit breaker protect against?", None),  # repeat -> cache hit
    (
        "Refactor this into a pure function:\n```python\ndef total(items):\n"
        "    global t\n    t = 0\n    for i in items:\n        t += i['qty']\n    return t\n```",
        None,
    ),
    ("ok thanks", None),
    ("List three reasons a p99 spike might not show up in p50.", "ab-split"),
]


async def _seed_catalogue() -> int:
    live = set(settings.live_providers)
    created = 0
    async with session_scope() as session:
        for entry in seed_catalogue():
            existing = await session.scalar(
                select(ModelEntry).where(ModelEntry.slug == entry["slug"])
            )
            if existing is not None:
                continue
            provider = entry["provider"]
            enabled = provider == "simulated" or provider in live
            session.add(
                ModelEntry(
                    **entry,
                    enabled=enabled,
                    price_verified_at=utcnow() if entry.get("price_source") else None,
                )
            )
            created += 1
    return created


async def _seed_policies() -> int:
    created = 0
    async with session_scope() as session:
        for entry in seed_policies():
            existing = await session.scalar(
                select(RoutingPolicy).where(RoutingPolicy.name == entry["name"])
            )
            if existing is not None:
                continue
            session.add(RoutingPolicy(**entry))
            created += 1
    return created


async def _seed_key() -> None:
    async with session_scope() as session:
        if await session.scalar(select(func.count()).select_from(ApiKey)):
            return
        token, prefix, hashed = mint_api_key()
        session.add(
            ApiKey(
                name="demo-client",
                prefix=prefix,
                hashed=hashed,
                policy="cost-optimised",
                rpm_limit=settings.default_rpm_limit,
                tpm_limit=settings.default_tpm_limit,
                monthly_budget_usd=settings.default_monthly_budget_usd,
            )
        )
        log.info("bootstrap: created data-plane API key -> %s", token)


async def _warm_traffic() -> None:
    """A handful of real calls so the dashboard is populated on first load."""
    for prompt, policy in WARMUP_PROMPTS:
        ctx = RequestContext(
            messages=[{"role": "user", "content": prompt}],
            policy=policy,
            temperature=0.2,
            max_tokens=180,
            stream=False,
            client="bootstrap",
            route="/bootstrap",
        )
        with contextlib.suppress(Exception):
            result = await gateway.complete(ctx)
            log.info(
                "bootstrap: %-14s -> %-14s %5.0fms  $%.6f  cache=%s",
                (result.decision.complexity or "?")[:14],
                result.model.slug,
                result.latency_ms,
                result.cost_usd,
                result.cache_state,
            )
        await asyncio.sleep(0.05)


async def seed() -> None:
    models = await _seed_catalogue()
    policies = await _seed_policies()
    if models or policies:
        log.info("bootstrap: seeded %s catalogue rows, %s policies", models, policies)
    log.info("bootstrap: providers -> %s", ", ".join(sorted(providers.registry())))

    if not settings.bootstrap_demo:
        return
    await _seed_key()

    async with session_scope() as session:
        from .models import InferenceRequest

        existing = int(
            await session.scalar(select(func.count()).select_from(InferenceRequest)) or 0
        )
    if existing:
        log.info("bootstrap: %s requests already logged, skipping warm-up", existing)
        return
    await _warm_traffic()
    log.info("bootstrap: warm-up traffic complete")


def schedule(delay: float = 2.0) -> asyncio.Task[None]:
    async def _task() -> None:
        await asyncio.sleep(delay)
        try:
            await seed()
        except Exception:
            log.exception("bootstrap failed")

    return asyncio.create_task(_task(), name="sentinel-bootstrap")
