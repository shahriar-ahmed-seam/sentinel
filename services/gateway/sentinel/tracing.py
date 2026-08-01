"""Span recording with W3C-compatible ids.

Spans are always persisted locally so the built-in waterfall viewer works with
no collector to operate. When `OTEL_EXPORTER_OTLP_ENDPOINT` is configured and
the OpenTelemetry SDK is installed (see requirements-optional.txt) the same
spans are mirrored out, so Sentinel drops into an existing Jaeger/Tempo/Grafana
pipeline without changing application code.

Incoming `traceparent` headers are honoured, which means a caller's trace id
flows through the gateway into the provider span — the whole point of doing this
properly rather than inventing a private id scheme.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete

from .db import session_scope
from .models import Span, utcnow
from .observability import spans_recorded, trace_overhead
from .settings import settings

log = logging.getLogger("sentinel.tracing")

current_trace_id: ContextVar[str] = ContextVar("current_trace_id", default="")
current_span_id: ContextVar[str | None] = ContextVar("current_span_id", default=None)


def new_trace_id() -> str:
    return secrets.token_hex(16)


def new_span_id() -> str:
    return secrets.token_hex(8)


def parse_traceparent(header: str | None) -> tuple[str, str] | None:
    """Return (trace_id, parent_span_id) from a W3C traceparent header."""
    if not header:
        return None
    parts = header.strip().split("-")
    if len(parts) < 4 or len(parts[1]) != 32 or len(parts[2]) != 16:
        return None
    if parts[1] == "0" * 32 or parts[2] == "0" * 16:
        return None
    return parts[1], parts[2]


def traceparent(trace_id: str, span_id: str, sampled: bool = True) -> str:
    return f"00-{trace_id}-{span_id}-{'01' if sampled else '00'}"


@dataclass
class SpanHandle:
    span_id: str
    trace_id: str
    name: str
    started: float
    parent_id: str | None = None
    request_id: str | None = None
    kind: str = "internal"
    status: str = "ok"
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    start_wall: datetime = field(default_factory=utcnow)

    def set(self, **attributes: Any) -> None:
        for key, value in attributes.items():
            if value is not None:
                self.attributes[key] = value

    def event(self, name: str, **attributes: Any) -> None:
        self.events.append(
            {
                "name": name,
                "at": utcnow().isoformat(),
                "offset_ms": round((time.perf_counter() - self.started) * 1000, 3),
                **{k: v for k, v in attributes.items() if v is not None},
            }
        )

    def fail(self, error: BaseException | str) -> None:
        self.status = "error"
        self.attributes["error"] = str(error)[:400]

    @property
    def traceparent(self) -> str:
        return traceparent(self.trace_id, self.span_id)


class Tracer:
    """Buffers spans and flushes them in batches off the request path."""

    def __init__(self) -> None:
        self._buffer: list[Span] = []
        self._lock = asyncio.Lock()
        self._flusher: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._otel = None
        self.dropped = 0

    # -- lifecycle -------------------------------------------------------
    async def start(self) -> None:
        self._stop.clear()
        self._flusher = asyncio.create_task(self._loop(), name="sentinel-span-flusher")
        self._init_otel()

    async def stop(self) -> None:
        self._stop.set()
        if self._flusher:
            self._flusher.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._flusher
            self._flusher = None
        await self.flush()

    def _init_otel(self) -> None:
        endpoint = settings.otel_exporter_otlp_endpoint
        if not endpoint:
            return
        try:  # pragma: no cover - optional dependency
            from opentelemetry import trace as otel_trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint)
            provider = TracerProvider(
                resource=Resource.create(
                    {
                        "service.name": settings.otel_service_name,
                        "service.version": settings.app_version,
                        "deployment.environment": settings.app_env,
                    }
                )
            )
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
            otel_trace.set_tracer_provider(provider)
            self._otel = otel_trace.get_tracer("sentinel")
            log.info("OTLP span export enabled -> %s", endpoint)
        except Exception as exc:
            log.warning(
                "OTLP export requested but unavailable (%s). Spans stay local. "
                "Install requirements-optional.txt to enable it.",
                exc,
            )

    # -- api -------------------------------------------------------------
    @asynccontextmanager
    async def span(
        self,
        name: str,
        *,
        kind: str = "internal",
        request_id: str | None = None,
        trace_id: str | None = None,
        parent_id: str | None = None,
        **attributes: Any,
    ) -> AsyncIterator[SpanHandle]:
        resolved_trace = trace_id or current_trace_id.get() or new_trace_id()
        handle = SpanHandle(
            span_id=new_span_id(),
            trace_id=resolved_trace,
            name=name,
            started=time.perf_counter(),
            parent_id=parent_id if parent_id is not None else current_span_id.get(),
            request_id=request_id,
            kind=kind,
            attributes={k: v for k, v in attributes.items() if v is not None},
        )
        trace_token = current_trace_id.set(resolved_trace)
        span_token = current_span_id.set(handle.span_id)
        try:
            yield handle
        except BaseException as exc:
            handle.fail(exc)
            raise
        finally:
            current_span_id.reset(span_token)
            current_trace_id.reset(trace_token)
            await self.record(handle)

    async def record(self, handle: SpanHandle) -> None:
        from .runtime import config

        if not config.tracing_enabled:
            return
        duration_ms = (time.perf_counter() - handle.started) * 1000
        row = Span(
            id=handle.span_id,
            trace_id=handle.trace_id,
            parent_id=handle.parent_id,
            request_id=handle.request_id,
            name=handle.name,
            kind=handle.kind,
            status=handle.status,
            started_at=handle.start_wall,
            ended_at=utcnow(),
            duration_ms=round(duration_ms, 3),
            attributes=handle.attributes,
            events=handle.events,
        )
        async with self._lock:
            if len(self._buffer) >= 5000:
                self.dropped += 1
                return
            self._buffer.append(row)
        spans_recorded.inc()
        self._mirror(handle, duration_ms)

    def _mirror(self, handle: SpanHandle, duration_ms: float) -> None:
        if self._otel is None:
            return
        try:  # pragma: no cover - optional dependency
            with self._otel.start_as_current_span(handle.name) as span:
                for key, value in handle.attributes.items():
                    span.set_attribute(f"sentinel.{key}", str(value))
                span.set_attribute("sentinel.duration_ms", duration_ms)
                span.set_attribute("sentinel.trace_ref", handle.trace_id)
        except Exception:
            self._otel = None

    async def flush(self) -> int:
        async with self._lock:
            batch, self._buffer = self._buffer, []
        if not batch:
            return 0
        started = time.perf_counter()
        try:
            async with session_scope() as session:
                session.add_all(batch)
        except Exception as exc:
            log.warning("span flush failed (%s spans dropped): %s", len(batch), exc)
            self.dropped += len(batch)
            return 0
        trace_overhead.observe(time.perf_counter() - started)
        return len(batch)

    async def _loop(self) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(1.0)
            try:
                await self.flush()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("span flusher error")

    async def prune(self) -> int:
        cutoff = utcnow() - timedelta(hours=settings.trace_retention_hours)
        async with session_scope() as session:
            result = await session.execute(delete(Span).where(Span.started_at < cutoff))
        return int(result.rowcount or 0)

    @property
    def buffered(self) -> int:
        return len(self._buffer)


tracer = Tracer()
