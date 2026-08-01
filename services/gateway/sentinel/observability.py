"""Prometheus instrumentation, structured logging and request middleware."""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware

from .settings import settings

REGISTRY = CollectorRegistry(auto_describe=True)

LATENCY_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 60.0)
TTFT_BUCKETS = (0.02, 0.05, 0.1, 0.2, 0.35, 0.5, 0.75, 1.0, 1.5, 2.5, 5.0, 10.0)

http_requests = Counter(
    "sentinel_http_requests_total",
    "HTTP requests handled by the gateway.",
    ["method", "route", "status"],
    registry=REGISTRY,
)
http_latency = Histogram(
    "sentinel_http_request_duration_seconds",
    "HTTP request latency.",
    ["method", "route"],
    buckets=LATENCY_BUCKETS,
    registry=REGISTRY,
)
inferences = Counter(
    "sentinel_inferences_total",
    "Model calls by resolved model, provider, cache state and status.",
    ["model", "provider", "cache", "status"],
    registry=REGISTRY,
)
inference_latency = Histogram(
    "sentinel_inference_duration_seconds",
    "End-to-end model call latency as seen by the caller.",
    ["model", "provider"],
    buckets=LATENCY_BUCKETS,
    registry=REGISTRY,
)
ttft = Histogram(
    "sentinel_time_to_first_token_seconds",
    "Time to first token.",
    ["model", "provider"],
    buckets=TTFT_BUCKETS,
    registry=REGISTRY,
)
tokens = Counter(
    "sentinel_tokens_total",
    "Tokens accounted for, by direction.",
    ["model", "provider", "direction"],
    registry=REGISTRY,
)
cost = Counter(
    "sentinel_cost_usd_total",
    "Attributed spend in USD.",
    ["model", "provider"],
    registry=REGISTRY,
)
savings = Counter(
    "sentinel_savings_usd_total",
    "Spend avoided versus the premium-baseline model, by source.",
    ["source"],
    registry=REGISTRY,
)
throughput = Histogram(
    "sentinel_output_tokens_per_second",
    "Generation throughput per completed call.",
    ["model"],
    buckets=(5, 10, 20, 40, 60, 90, 130, 200, 320, 600),
    registry=REGISTRY,
)
retries = Counter(
    "sentinel_upstream_retries_total",
    "Upstream retry attempts.",
    ["provider", "reason"],
    registry=REGISTRY,
)
circuit_state = Gauge(
    "sentinel_circuit_state",
    "Circuit breaker state per provider (0 closed, 1 half-open, 2 open).",
    ["provider"],
    registry=REGISTRY,
)
inflight = Gauge(
    "sentinel_inflight_requests",
    "Model calls currently in flight. Scale on this.",
    registry=REGISTRY,
)
queue_wait = Histogram(
    "sentinel_concurrency_wait_seconds",
    "Time spent waiting for a concurrency slot.",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0),
    registry=REGISTRY,
)
cache_ops = Counter(
    "sentinel_cache_operations_total",
    "Response cache outcomes.",
    ["outcome"],
    registry=REGISTRY,
)
rate_limited = Counter(
    "sentinel_rate_limited_total",
    "Requests rejected by a limit.",
    ["reason"],
    registry=REGISTRY,
)
guard_blocks = Counter(
    "sentinel_guard_blocks_total",
    "Requests altered or rejected by guardrails.",
    ["rule", "action"],
    registry=REGISTRY,
)
spans_recorded = Counter(
    "sentinel_spans_recorded_total",
    "Spans persisted by the tracer.",
    registry=REGISTRY,
)
trace_overhead = Histogram(
    "sentinel_trace_flush_seconds",
    "Time spent persisting spans (the measurable cost of tracing).",
    buckets=(0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1),
    registry=REGISTRY,
)
build_info = Gauge(
    "sentinel_build_info",
    "Build metadata (always 1).",
    ["version", "git_sha", "env", "region"],
    registry=REGISTRY,
)
build_info.labels(settings.app_version, settings.git_sha, settings.app_env, settings.region).set(1)


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


# --------------------------------------------------------------------------- #
# logging
# --------------------------------------------------------------------------- #
class _Formatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = (
            f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:<7} "
            f"{record.name:<24} {record.getMessage()}"
        )
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_Formatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())
    for noisy in ("uvicorn.access", "sqlalchemy.engine.Engine", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# --------------------------------------------------------------------------- #
# middleware
# --------------------------------------------------------------------------- #
def _route_label(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", None) or request.url.path


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        from .tracing import current_trace_id, new_trace_id, parse_traceparent

        incoming = parse_traceparent(request.headers.get("traceparent"))
        trace_id = incoming[0] if incoming else new_trace_id()
        request.state.trace_id = trace_id
        request.state.parent_span_id = incoming[1] if incoming else None
        token = current_trace_id.set(trace_id)

        started = time.perf_counter()
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            elapsed = time.perf_counter() - started
            route = _route_label(request)
            http_requests.labels(request.method, route, "500").inc()
            http_latency.labels(request.method, route).observe(elapsed)
            current_trace_id.reset(token)
            raise
        elapsed = time.perf_counter() - started
        route = _route_label(request)
        if route != "/metrics":
            http_requests.labels(request.method, route, str(status_code)).inc()
            http_latency.labels(request.method, route).observe(elapsed)
        response.headers["x-trace-id"] = trace_id
        response.headers["server-timing"] = f"gateway;dur={elapsed * 1000:.2f}"
        current_trace_id.reset(token)
        return response
