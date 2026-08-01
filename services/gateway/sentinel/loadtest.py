"""Built-in load generator.

Drives the gateway pipeline directly (guard -> route -> cache -> upstream ->
accounting) rather than looping over HTTP. That is deliberate: the numbers this
produces are about the gateway, not about uvicorn, and an in-process harness
needs no self-referential URL to work inside a container or in CI.

Two things get measured that are otherwise hand-waved:

* **Concurrency ramp** — sustained requests/second and TTFT percentiles at
  1, 2, 4, ... N concurrent callers, which is the evidence behind an autoscaling
  claim.
* **Tracing overhead** — the same stage run with span recording on and off, so
  "tracing is cheap" becomes a percentage instead of an assertion.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

from .db import session_scope
from .events import bus
from .gateway import GatewayError, RequestContext, gateway
from .limits import limiter
from .models import LoadTest, utcnow
from .runtime import config as runtime_config

log = logging.getLogger("sentinel.loadtest")

PROMPTS = [
    "Summarise what a circuit breaker does in one sentence.",
    "List three reasons a p99 latency spike might not show up in p50.",
    "ok thanks",
    "Explain step by step how to decide between a read replica and a cache for a "
    "read-heavy endpoint, and analyse the failure modes of each choice.",
    "Refactor this into a pure function:\n```python\ndef total(items):\n    global t\n"
    "    t = 0\n    for i in items:\n        t += i['qty'] * i['price']\n    return t\n```",
    "What is the difference between a rate limit and a quota?",
    "Derive the expected cost per thousand requests if 60% are cache hits and the "
    "miss path costs $0.0004, then optimise the ratio for a $50 monthly budget.",
    "hey",
    "Draft a one-paragraph incident note for a 4-minute upstream outage that was "
    "absorbed by failover with no customer-visible errors.",
    "Which HTTP status codes should a gateway retry, and why not 400?",
]


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((p / 100) * (len(ordered) - 1)))))
    return round(ordered[index], 3)


@dataclass
class Sample:
    ok: bool
    latency_ms: float
    ttft_ms: float = 0.0
    overhead_ms: float = 0.0
    tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    cache: str = ""
    error: str = ""


@dataclass
class StageResult:
    concurrency: int
    requests: int
    completed: int
    failed: int
    duration_s: float
    rps: float
    ttft_p50: float
    ttft_p95: float
    ttft_p99: float
    latency_p50: float
    latency_p95: float
    latency_p99: float
    overhead_p50: float
    overhead_p95: float
    tokens: int
    cost_usd: float
    cache_hits: int
    peak_inflight: int
    models: dict[str, int] = field(default_factory=dict)
    errors: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__


class LoadTester:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self.current: str | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def submit(
        self,
        *,
        label: str,
        policy: str | None,
        model: str | None,
        concurrency_levels: list[int],
        requests_per_stage: int,
        max_tokens: int,
        measure_tracing_overhead: bool,
        actor: str,
    ) -> str:
        if self.running:
            raise RuntimeError("a load test is already running")

        cfg = {
            "policy": policy,
            "model": model,
            "concurrency_levels": concurrency_levels,
            "requests_per_stage": requests_per_stage,
            "max_tokens": max_tokens,
            "measure_tracing_overhead": measure_tracing_overhead,
            "harness": "in-process (gateway pipeline, no HTTP hop)",
            "actor": actor,
        }
        async with session_scope() as session:
            row = LoadTest(label=label or "concurrency ramp", status="queued", config=cfg)
            session.add(row)
            await session.flush()
            test_id = row.id

        self._task = asyncio.create_task(
            self._run(test_id, cfg), name=f"sentinel-loadtest-{test_id[:8]}"
        )
        return test_id

    async def _run(self, test_id: str, cfg: dict[str, Any]) -> None:
        self.current = test_id
        started = time.perf_counter()
        stages: list[dict[str, Any]] = []
        try:
            async with session_scope() as session:
                row = await session.get(LoadTest, test_id)
                if row is not None:
                    row.status = "running"
                    row.started_at = utcnow()

            for level in cfg["concurrency_levels"]:
                stage = await self._stage(
                    concurrency=level,
                    requests=cfg["requests_per_stage"],
                    policy=cfg["policy"],
                    model=cfg["model"],
                    max_tokens=cfg["max_tokens"],
                    label=f"c{level}",
                )
                stages.append(stage.as_dict())
                await bus.publish(
                    "loadtest.stage",
                    {"test_id": test_id, "concurrency": level, "rps": stage.rps},
                )
                async with session_scope() as session:
                    row = await session.get(LoadTest, test_id)
                    if row is not None:
                        row.stages = stages

            overhead: dict[str, Any] = {}
            if cfg["measure_tracing_overhead"]:
                # Measured at low concurrency on purpose: once the event loop
                # saturates, gateway overhead is queueing delay and the span
                # cost is unmeasurable underneath it.
                overhead = await self._tracing_overhead(
                    concurrency=min(4, max(cfg["concurrency_levels"])),
                    requests=max(40, cfg["requests_per_stage"]),
                    policy=cfg["policy"],
                    model=cfg["model"],
                    max_tokens=cfg["max_tokens"],
                )

            summary = self._summarise(stages, overhead)
            duration_ms = int((time.perf_counter() - started) * 1000)
            async with session_scope() as session:
                row = await session.get(LoadTest, test_id)
                if row is not None:
                    row.status = "succeeded"
                    row.stages = stages
                    row.summary = summary
                    row.finished_at = utcnow()
                    row.duration_ms = duration_ms
            await bus.publish(
                "loadtest.finished",
                {"test_id": test_id, "status": "succeeded", **summary},
            )
            log.info("load test %s finished in %sms: %s", test_id[:8], duration_ms, summary)
        except asyncio.CancelledError:
            await self._mark_failed(test_id, "cancelled")
            raise
        except Exception as exc:
            log.exception("load test %s failed", test_id[:8])
            await self._mark_failed(test_id, f"{exc.__class__.__name__}: {exc}")
        finally:
            self.current = None

    async def _mark_failed(self, test_id: str, error: str) -> None:
        async with session_scope() as session:
            row = await session.get(LoadTest, test_id)
            if row is not None:
                row.status = "failed"
                row.error = error[:2000]
                row.finished_at = utcnow()
        await bus.publish("loadtest.finished", {"test_id": test_id, "status": "failed"})

    async def _stage(
        self,
        *,
        concurrency: int,
        requests: int,
        policy: str | None,
        model: str | None,
        max_tokens: int,
        label: str,
    ) -> StageResult:
        semaphore = asyncio.Semaphore(concurrency)
        samples: list[Sample] = []
        rng = random.Random(f"{label}-{requests}")
        limiter.peak_inflight = 0

        async def one(index: int) -> None:
            async with semaphore:
                prompt = PROMPTS[index % len(PROMPTS)]
                # Unique nonce keeps every call a genuine cache miss, so the
                # stage measures the upstream path rather than the cache.
                nonce = rng.randrange(10**9)
                ctx = RequestContext(
                    messages=[{"role": "user", "content": f"{prompt}\n\n[trace {nonce}]"}],
                    model=model,
                    policy=policy,
                    temperature=0.6,
                    max_tokens=max_tokens,
                    stream=False,
                    cache=False,
                    client=f"loadtest:{label}",
                    route="/loadtest",
                    redact=False,
                )
                started = time.perf_counter()
                try:
                    result = await gateway.complete(ctx)
                    samples.append(
                        Sample(
                            ok=True,
                            latency_ms=result.latency_ms,
                            ttft_ms=result.ttft_ms,
                            overhead_ms=result.overhead_ms,
                            tokens=result.total_tokens,
                            cost_usd=result.cost_usd,
                            model=result.model.slug,
                            cache=result.cache_state,
                        )
                    )
                except GatewayError as exc:
                    samples.append(
                        Sample(
                            ok=False,
                            latency_ms=(time.perf_counter() - started) * 1000,
                            error=exc.reason,
                        )
                    )
                except Exception as exc:
                    samples.append(
                        Sample(
                            ok=False,
                            latency_ms=(time.perf_counter() - started) * 1000,
                            error=exc.__class__.__name__,
                        )
                    )

        wall_start = time.perf_counter()
        await asyncio.gather(*(one(i) for i in range(requests)))
        duration = time.perf_counter() - wall_start

        ok = [s for s in samples if s.ok]
        failed = [s for s in samples if not s.ok]
        models: dict[str, int] = {}
        errors: dict[str, int] = {}
        for sample in ok:
            models[sample.model] = models.get(sample.model, 0) + 1
        for sample in failed:
            errors[sample.error] = errors.get(sample.error, 0) + 1

        return StageResult(
            concurrency=concurrency,
            requests=requests,
            completed=len(ok),
            failed=len(failed),
            duration_s=round(duration, 3),
            rps=round(len(ok) / max(duration, 1e-6), 2),
            ttft_p50=percentile([s.ttft_ms for s in ok], 50),
            ttft_p95=percentile([s.ttft_ms for s in ok], 95),
            ttft_p99=percentile([s.ttft_ms for s in ok], 99),
            latency_p50=percentile([s.latency_ms for s in ok], 50),
            latency_p95=percentile([s.latency_ms for s in ok], 95),
            latency_p99=percentile([s.latency_ms for s in ok], 99),
            overhead_p50=percentile([s.overhead_ms for s in ok], 50),
            overhead_p95=percentile([s.overhead_ms for s in ok], 95),
            tokens=sum(s.tokens for s in ok),
            cost_usd=round(sum(s.cost_usd for s in ok), 6),
            cache_hits=sum(1 for s in ok if s.cache == "hit"),
            peak_inflight=limiter.peak_inflight,
            models=models,
            errors=errors,
        )

    async def _tracing_overhead(
        self,
        *,
        concurrency: int,
        requests: int,
        policy: str | None,
        model: str | None,
        max_tokens: int,
    ) -> dict[str, Any]:
        original = runtime_config.tracing_enabled
        try:
            runtime_config.tracing_enabled = True
            with_tracing = await self._stage(
                concurrency=concurrency,
                requests=requests,
                policy=policy,
                model=model,
                max_tokens=max_tokens,
                label="trace-on",
            )
            runtime_config.tracing_enabled = False
            without = await self._stage(
                concurrency=concurrency,
                requests=requests,
                policy=policy,
                model=model,
                max_tokens=max_tokens,
                label="trace-off",
            )
        finally:
            runtime_config.tracing_enabled = original

        # Compare the gateway's own overhead, not end-to-end latency: upstream
        # time dominates the total and is stochastic, which would drown the
        # signal being measured.
        delta = with_tracing.overhead_p50 - without.overhead_p50
        ratio = delta / max(without.overhead_p50, 1e-6)
        return {
            "concurrency": concurrency,
            "requests_per_arm": requests,
            "metric": "gateway overhead (total latency minus upstream time)",
            "overhead_p50_with_tracing_ms": with_tracing.overhead_p50,
            "overhead_p50_without_tracing_ms": without.overhead_p50,
            "overhead_p95_with_tracing_ms": with_tracing.overhead_p95,
            "overhead_p95_without_tracing_ms": without.overhead_p95,
            "delta_ms": round(delta, 3),
            "overhead_ratio": round(ratio, 5),
            "latency_p50_with_tracing_ms": with_tracing.latency_p50,
            "latency_p50_without_tracing_ms": without.latency_p50,
            "rps_with_tracing": with_tracing.rps,
            "rps_without_tracing": without.rps,
            "note": (
                "Spans are buffered in memory and flushed off the request path, so the "
                "delta reflects span construction rather than database I/O. Small "
                "sample sizes are noisy — raise requests_per_stage for a tighter number."
            ),
        }

    @staticmethod
    def _summarise(stages: list[dict[str, Any]], overhead: dict[str, Any]) -> dict[str, Any]:
        if not stages:
            return {}
        completed = sum(s["completed"] for s in stages)
        failed = sum(s["failed"] for s in stages)
        best = max(stages, key=lambda s: s["rps"])
        slo = runtime_config.slo_ttft_ms
        within = [s for s in stages if s["ttft_p95"] <= slo and s["failed"] == 0]
        sustained = max(within, key=lambda s: s["rps"]) if within else None
        return {
            "stages": len(stages),
            "requests": completed + failed,
            "completed": completed,
            "failed": failed,
            "error_rate": round(failed / max(completed + failed, 1), 5),
            "peak_rps": best["rps"],
            "peak_rps_concurrency": best["concurrency"],
            "sustained_rps_within_slo": sustained["rps"] if sustained else None,
            "sustained_concurrency": sustained["concurrency"] if sustained else None,
            "slo_ttft_ms": slo,
            "tokens": sum(s["tokens"] for s in stages),
            "cost_usd": round(sum(s["cost_usd"] for s in stages), 6),
            "tracing_overhead": overhead or None,
        }


load_tester = LoadTester()
