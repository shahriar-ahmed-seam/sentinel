"""Cost, latency and routing analytics."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import cache as response_cache
from ..circuit import circuits
from ..db import get_session
from ..limits import limiter
from ..models import ApiKey, InferenceRequest, ModelEntry, utcnow
from ..runtime import config as runtime_config
from ..security import Principal, allow_read
from ..tracing import tracer

router = APIRouter(prefix="/api", tags=["analytics"])


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((p / 100) * (len(ordered) - 1)))))
    return round(float(ordered[index]), 3)


def _bucket(moment: datetime, minutes: int) -> datetime:
    epoch = int(moment.timestamp())
    size = minutes * 60
    return datetime.fromtimestamp(epoch - epoch % size, tz=moment.tzinfo)


@router.get("/overview")
async def overview(
    hours: int = Query(default=24, ge=1, le=720),
    bucket_minutes: int = Query(default=15, ge=1, le=1440),
    session: AsyncSession = Depends(get_session),
    _: Principal = Depends(allow_read),
) -> dict[str, Any]:
    since = utcnow() - timedelta(hours=hours)
    rows = (
        await session.execute(
            select(
                InferenceRequest.created_at,
                InferenceRequest.resolved_model,
                InferenceRequest.provider,
                InferenceRequest.policy,
                InferenceRequest.status,
                InferenceRequest.cache_state,
                InferenceRequest.complexity,
                InferenceRequest.prompt_tokens,
                InferenceRequest.completion_tokens,
                InferenceRequest.cost_usd,
                InferenceRequest.baseline_cost_usd,
                InferenceRequest.saved_usd,
                InferenceRequest.ttft_ms,
                InferenceRequest.latency_ms,
                InferenceRequest.overhead_ms,
                InferenceRequest.tokens_per_second,
            )
            .where(
                InferenceRequest.created_at >= since,
                InferenceRequest.shadow_of.is_(None),
            )
            .order_by(InferenceRequest.created_at.desc())
            .limit(80_000)
        )
    ).all()

    total = len(rows)
    ok_rows = [r for r in rows if r.status == "ok"]
    failed = total - len(ok_rows)
    served = [r for r in ok_rows if r.cache_state != "hit"]

    ttfts = [r.ttft_ms for r in served if r.ttft_ms]
    latencies = [r.latency_ms for r in ok_rows if r.latency_ms]
    overheads = [r.overhead_ms for r in served if r.overhead_ms]
    spend = sum(r.cost_usd for r in rows)
    baseline = sum(r.baseline_cost_usd for r in rows)
    saved = sum(r.saved_usd for r in rows)
    tokens_in = sum(r.prompt_tokens for r in rows)
    tokens_out = sum(r.completion_tokens for r in rows)

    buckets: dict[datetime, dict[str, Any]] = defaultdict(
        lambda: {
            "requests": 0,
            "errors": 0,
            "cache_hits": 0,
            "cost": 0.0,
            "saved": 0.0,
            "tokens": 0,
            "ttft": [],
            "latency": [],
        }
    )
    for row in rows:
        entry = buckets[_bucket(row.created_at, bucket_minutes)]
        entry["requests"] += 1
        entry["cost"] += row.cost_usd
        entry["saved"] += row.saved_usd
        entry["tokens"] += row.prompt_tokens + row.completion_tokens
        if row.status != "ok":
            entry["errors"] += 1
        if row.cache_state == "hit":
            entry["cache_hits"] += 1
        if row.ttft_ms:
            entry["ttft"].append(row.ttft_ms)
        if row.latency_ms:
            entry["latency"].append(row.latency_ms)

    series = [
        {
            "t": key.isoformat(),
            "requests": value["requests"],
            "errors": value["errors"],
            "cache_hits": value["cache_hits"],
            "cost_usd": round(value["cost"], 6),
            "saved_usd": round(value["saved"], 6),
            "tokens": value["tokens"],
            "ttft_p50": _percentile(value["ttft"], 50),
            "ttft_p95": _percentile(value["ttft"], 95),
            "latency_p95": _percentile(value["latency"], 95),
        }
        for key, value in sorted(buckets.items())
    ]

    by_model: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"requests": 0, "cost": 0.0, "tokens": 0, "ttft": [], "latency": [], "tps": []}
    )
    for row in rows:
        if not row.resolved_model:
            continue
        entry = by_model[row.resolved_model]
        entry["requests"] += 1
        entry["cost"] += row.cost_usd
        entry["tokens"] += row.prompt_tokens + row.completion_tokens
        entry["provider"] = row.provider
        if row.ttft_ms:
            entry["ttft"].append(row.ttft_ms)
        if row.latency_ms:
            entry["latency"].append(row.latency_ms)
        if row.tokens_per_second:
            entry["tps"].append(row.tokens_per_second)

    models = sorted(
        (
            {
                "model": slug,
                "provider": value.get("provider", ""),
                "requests": value["requests"],
                "share": round(value["requests"] / max(total, 1), 4),
                "cost_usd": round(value["cost"], 6),
                "tokens": value["tokens"],
                "ttft_p50": _percentile(value["ttft"], 50),
                "ttft_p95": _percentile(value["ttft"], 95),
                "latency_p95": _percentile(value["latency"], 95),
                "tokens_per_second": round(sum(value["tps"]) / len(value["tps"]), 2)
                if value["tps"]
                else 0.0,
            }
            for slug, value in by_model.items()
        ),
        key=lambda item: -item["requests"],
    )

    complexity_mix: dict[str, int] = defaultdict(int)
    policy_mix: dict[str, int] = defaultdict(int)
    for row in rows:
        if row.complexity:
            complexity_mix[row.complexity] += 1
        if row.policy:
            policy_mix[row.policy] += 1

    slo_target = runtime_config.slo_ttft_ms
    within_slo = sum(1 for value in ttfts if value <= slo_target)
    availability = len(ok_rows) / max(total, 1)

    return {
        "generated_at": utcnow().isoformat(),
        "window_hours": hours,
        "traffic": {
            "requests": total,
            "succeeded": len(ok_rows),
            "failed": failed,
            "error_rate": round(failed / max(total, 1), 5),
            "cache_hits": sum(1 for r in rows if r.cache_state == "hit"),
            "cache_hit_rate": round(
                sum(1 for r in rows if r.cache_state == "hit") / max(total, 1), 4
            ),
            "requests_per_minute": round(total / max(hours * 60, 1), 3),
        },
        "latency": {
            "ttft_p50": _percentile(ttfts, 50),
            "ttft_p95": _percentile(ttfts, 95),
            "ttft_p99": _percentile(ttfts, 99),
            "latency_p50": _percentile(latencies, 50),
            "latency_p95": _percentile(latencies, 95),
            "latency_p99": _percentile(latencies, 99),
            "gateway_overhead_p50": _percentile(overheads, 50),
            "gateway_overhead_p95": _percentile(overheads, 95),
        },
        "spend": {
            "cost_usd": round(spend, 6),
            "baseline_usd": round(baseline, 6),
            "saved_usd": round(saved, 6),
            "savings_ratio": round(saved / baseline, 4) if baseline else 0.0,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_per_1k_tokens": round(spend / max((tokens_in + tokens_out) / 1000, 1e-9), 6),
        },
        "slo": {
            "ttft_target_ms": slo_target,
            "ttft_attainment": round(within_slo / max(len(ttfts), 1), 4),
            "availability_target": runtime_config.slo_availability,
            "availability": round(availability, 5),
            "error_budget_remaining": round(
                1 - ((1 - availability) / max(1 - runtime_config.slo_availability, 1e-9)),
                4,
            ),
        },
        "series": series,
        "models": models,
        "mix": {
            "complexity": dict(sorted(complexity_mix.items())),
            "policy": dict(sorted(policy_mix.items(), key=lambda kv: -kv[1])),
        },
        "providers": circuits.all(),
        "concurrency": limiter.snapshot(),
        "cache": await response_cache.stats(session),
        "tracing": {
            "enabled": runtime_config.tracing_enabled,
            "buffered_spans": tracer.buffered,
            "dropped_spans": tracer.dropped,
            "retention_hours": None,
        },
    }


@router.get("/analytics/savings")
async def savings(
    hours: int = Query(default=168, ge=1, le=2160),
    session: AsyncSession = Depends(get_session),
    _: Principal = Depends(allow_read),
) -> dict[str, Any]:
    """Where the avoided spend came from: routing versus caching."""
    since = utcnow() - timedelta(hours=hours)
    rows = (
        await session.execute(
            select(
                InferenceRequest.cache_state,
                InferenceRequest.resolved_model,
                func.count().label("n"),
                func.coalesce(func.sum(InferenceRequest.cost_usd), 0.0),
                func.coalesce(func.sum(InferenceRequest.baseline_cost_usd), 0.0),
                func.coalesce(func.sum(InferenceRequest.saved_usd), 0.0),
            )
            .where(
                InferenceRequest.created_at >= since,
                InferenceRequest.shadow_of.is_(None),
                InferenceRequest.status == "ok",
            )
            .group_by(InferenceRequest.cache_state, InferenceRequest.resolved_model)
        )
    ).all()

    routing_saved = sum(r[5] for r in rows if r[0] != "hit")
    cache_saved = sum(r[5] for r in rows if r[0] == "hit")
    spend = sum(r[3] for r in rows)
    baseline = sum(r[4] for r in rows)

    premium = await session.scalar(
        select(ModelEntry)
        .where(ModelEntry.enabled.is_(True))
        .order_by((ModelEntry.input_price_per_mtok + ModelEntry.output_price_per_mtok).desc())
        .limit(1)
    )

    return {
        "window_hours": hours,
        "baseline_model": premium.slug if premium else None,
        "baseline_usd": round(baseline, 6),
        "actual_usd": round(spend, 6),
        "saved_usd": round(routing_saved + cache_saved, 6),
        "saved_ratio": round((routing_saved + cache_saved) / baseline, 4) if baseline else 0.0,
        "by_source": {
            "routing": round(routing_saved, 6),
            "cache": round(cache_saved, 6),
        },
        "by_model": [
            {
                "model": row[1],
                "cache_state": row[0],
                "requests": int(row[2]),
                "cost_usd": round(float(row[3]), 6),
                "baseline_usd": round(float(row[4]), 6),
                "saved_usd": round(float(row[5]), 6),
            }
            for row in sorted(rows, key=lambda r: -float(r[5]))
        ],
        "method": (
            "Baseline is the counterfactual cost of sending the same tokens to the most "
            "expensive enabled model. Cache hits are credited with the full cost of the "
            "call they replaced."
        ),
    }


@router.get("/analytics/keys")
async def usage_by_key(
    session: AsyncSession = Depends(get_session),
    _: Principal = Depends(allow_read),
) -> dict[str, Any]:
    keys = list((await session.execute(select(ApiKey))).scalars())
    return {
        "keys": [
            {
                "id": key.id,
                "name": key.name,
                "prefix": key.prefix,
                "policy": key.policy,
                "requests": key.request_count,
                "tokens": key.token_count,
                "spent_usd": round(key.spent_usd, 6),
                "budget_usd": key.monthly_budget_usd,
                "budget_used": round(key.spent_usd / key.monthly_budget_usd, 4)
                if key.monthly_budget_usd
                else 0.0,
                "rpm_limit": key.rpm_limit,
                "tpm_limit": key.tpm_limit,
                "revoked": key.revoked,
                "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
            }
            for key in sorted(keys, key=lambda k: -k.spent_usd)
        ]
    }
