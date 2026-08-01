"""Sentinel gateway application."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from . import bootstrap, cache, providers, runtime
from .db import dispose_db, init_db, session_scope
from .observability import ObservabilityMiddleware, configure_logging
from .routers import ROUTERS
from .settings import settings
from .tracing import tracer

log = logging.getLogger("sentinel")

DESCRIPTION = """
**Sentinel** is a model-serving gateway with the observability an operator
actually needs.

* **Data plane** (`/v1/*`) - an OpenAI-compatible `/chat/completions` endpoint
  with streaming, so existing clients point at it unchanged.
* **Routing** - classify the prompt, then pick the cheapest (or fastest) model
  that can handle it, with weighted A/B, ordered failover and shadow traffic.
* **Resilience** - per-provider circuit breakers, bounded retries with jitter,
  concurrency admission control, rate limits and per-key budgets.
* **Accounting** - tokens and cost per request against an editable price book,
  plus the counterfactual cost of the premium model so savings are measurable.
* **Tracing** - W3C-compatible spans persisted locally for the built-in
  waterfall viewer, optionally mirrored to an OTLP collector.
* **Metrics** - Prometheus at `/metrics`; live feed at `/api/stream`.
"""


async def _janitor() -> None:
    """Retention and cache hygiene. Cheap, periodic, boring on purpose."""
    while True:
        await asyncio.sleep(300)
        try:
            pruned = await tracer.prune()
            async with session_scope() as session:
                expired = await cache.purge(session, expired_only=True)
                evicted = await cache.evict_overflow(session)
            if pruned or expired or evicted:
                log.info(
                    "janitor: %s spans pruned, %s cache entries expired, %s evicted",
                    pruned,
                    expired,
                    evicted,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("janitor pass failed")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    log.info(
        "starting %s %s (env=%s, db=%s, providers=%s)",
        settings.app_name,
        settings.app_version,
        settings.app_env,
        "postgres" if settings.is_postgres else "sqlite",
        ", ".join(sorted(providers.registry())) or "none",
    )
    await init_db()
    async with session_scope() as session:
        await runtime.load(session)
    await tracer.start()
    janitor = asyncio.create_task(_janitor(), name="sentinel-janitor")
    seeder = bootstrap.schedule()
    try:
        yield
    finally:
        for task in (seeder, janitor):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await tracer.stop()
        await providers.close_all()
        await dispose_db()
        log.info("shutdown complete")


app = FastAPI(
    title="Sentinel Gateway",
    description=DESCRIPTION,
    version=settings.app_version,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
    contact={"name": "Somokolon Labs"},
    license_info={"name": "MIT"},
)

app.add_middleware(ObservabilityMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=900)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-trace-id", "server-timing"],
)

for router in ROUTERS:
    app.include_router(router)


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": {"message": "Internal server error", "type": "internal"},
            "trace_id": getattr(request.state, "trace_id", ""),
        },
    )


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "chat": "/v1/chat/completions",
        "models": "/v1/models",
        "docs": "/docs",
        "health": "/health",
        "metrics": "/metrics",
        "stream": "/api/stream",
    }
