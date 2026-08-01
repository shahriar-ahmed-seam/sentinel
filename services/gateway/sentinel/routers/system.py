"""Health, metrics, system info and the live event stream."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from .. import providers
from ..circuit import circuits
from ..db import get_session
from ..events import EVENT_KINDS, bus, sse
from ..limits import limiter
from ..loadtest import load_tester
from ..models import utcnow
from ..observability import render_metrics
from ..runtime import config as runtime_config
from ..security import Principal, allow_read
from ..settings import settings
from ..tracing import tracer

router = APIRouter(tags=["system"])
STARTED_AT = time.time()


@router.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "env": settings.app_env,
        "region": settings.region,
        "uptime_seconds": round(time.time() - STARTED_AT, 1),
    }


@router.get("/health/ready")
async def readiness(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    ok = True
    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"
        ok = False

    configured = sorted(providers.registry())
    checks["providers"] = configured
    if not configured:
        ok = False
        checks["providers_error"] = "no provider adapters registered"

    open_circuits = [c["provider"] for c in circuits.all() if c["state"] == "open"]
    checks["open_circuits"] = open_circuits
    checks["inflight"] = limiter.current_inflight
    checks["tracing"] = runtime_config.tracing_enabled
    return {"status": "ready" if ok else "degraded", "checks": checks}


@router.get("/metrics")
async def metrics() -> Response:
    payload, content_type = render_metrics()
    return Response(content=payload, media_type=content_type)


@router.get("/api/system")
async def system_info(_: Principal = Depends(allow_read)) -> dict[str, Any]:
    return {
        "app": {
            "name": settings.app_name,
            "version": settings.app_version,
            "env": settings.app_env,
            "region": settings.region,
            "git_sha": settings.git_sha,
            "uptime_seconds": round(time.time() - STARTED_AT, 1),
        },
        "infrastructure": {
            "database": "postgres" if settings.is_postgres else "sqlite",
            "providers_configured": sorted(providers.registry()),
            "live_providers": settings.live_providers,
            "simulate_only": settings.simulate_only,
            "otlp_endpoint": settings.otel_exporter_otlp_endpoint or None,
            "event_subscribers": bus.subscriber_count,
            "event_kinds": list(EVENT_KINDS),
        },
        "concurrency": limiter.snapshot(),
        "tracing": {
            "enabled": runtime_config.tracing_enabled,
            "buffered_spans": tracer.buffered,
            "dropped_spans": tracer.dropped,
            "retention_hours": settings.trace_retention_hours,
            "otlp_mirroring": bool(settings.otel_exporter_otlp_endpoint),
        },
        "runtime": runtime_config.as_dict(),
        "providers": circuits.all(),
        "loadtest": {"running": load_tester.running, "current": load_tester.current},
        "limits": {
            "max_prompt_chars": settings.max_prompt_chars,
            "max_output_tokens_cap": settings.max_output_tokens_cap,
            "upstream_timeout_seconds": settings.upstream_timeout_seconds,
        },
    }


@router.get("/api/stream")
async def stream(request: Request) -> StreamingResponse:
    """Server-sent events: completions, routing decisions, circuits, load tests."""
    queue = await bus.subscribe()

    async def publisher():
        try:
            yield sse(
                {
                    "kind": "hello",
                    "at": utcnow().isoformat(),
                    "data": {"service": settings.app_name, "version": settings.app_version},
                }
            )
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield sse(event)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            with contextlib.suppress(Exception):
                await bus.unsubscribe(queue)

    return StreamingResponse(
        publisher(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
