"""The gateway hot path.

One pipeline, fully traced, for every model call:

    guard -> limits -> route -> cache -> attempt chain (retry + circuit) ->
    account (tokens, cost, savings) -> persist -> publish

The gateway opens its own database sessions rather than borrowing the request's.
A streaming response outlives the dependency scope, and accounting that happens
after the session closes is accounting that silently disappears.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from . import cache as response_cache
from . import providers
from .circuit import circuits
from .db import session_scope
from .events import bus
from .guard import GuardRejection, inspect_request, scrub_output
from .limits import LimitExceeded, limiter
from .models import ApiKey, InferenceRequest, ModelEntry, utcnow
from .observability import (
    cost as cost_metric,
)
from .observability import (
    inference_latency,
    inferences,
    throughput,
)
from .observability import (
    retries as retry_metric,
)
from .observability import (
    savings as savings_metric,
)
from .observability import (
    tokens as token_metric,
)
from .observability import (
    ttft as ttft_metric,
)
from .policy import RouteDecision, router
from .pricing import compute_cost, estimate_messages_tokens, estimate_tokens
from .providers import ChatCall, UpstreamError
from .settings import settings
from .tracing import tracer

log = logging.getLogger("sentinel.gateway")

PREVIEW_CHARS = 600


class GatewayError(Exception):
    def __init__(self, message: str, *, status_code: int = 502, reason: str = "upstream") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason


@dataclass
class RequestContext:
    messages: list[dict[str, Any]]
    model: str | None = None
    policy: str | None = None
    temperature: float = 0.7
    max_tokens: int | None = None
    top_p: float | None = None
    stop: list[str] | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    response_format: dict[str, Any] | None = None
    stream: bool = False
    cache: bool | None = None
    required_capabilities: list[str] = field(default_factory=list)
    subject: str = "anonymous"
    api_key_id: str | None = None
    client: str = "anonymous"
    trace_id: str = ""
    parent_span_id: str | None = None
    route: str = "/v1/chat/completions"
    redact: bool = True


@dataclass
class Attempt:
    model: str
    provider: str
    ok: bool
    ms: float
    error: str = ""
    retryable: bool = False


@dataclass
class GatewayResult:
    request_id: str
    trace_id: str
    model: ModelEntry
    text: str
    reasoning: str
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int
    cached_prompt_tokens: int
    cost_usd: float
    baseline_cost_usd: float
    saved_usd: float
    ttft_ms: float
    latency_ms: float
    upstream_ms: float
    overhead_ms: float
    tokens_per_second: float
    cache_state: str
    decision: RouteDecision
    attempts: list[Attempt]
    guard_flags: list[str]

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def openai_payload(self) -> dict[str, Any]:
        return {
            "id": f"chatcmpl-{self.request_id}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self.model.slug,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": self.text},
                    "finish_reason": self.finish_reason,
                }
            ],
            "usage": {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
                "prompt_tokens_details": {"cached_tokens": self.cached_prompt_tokens},
            },
            # Vendor extension: everything an operator needs without a second call.
            "sentinel": {
                "request_id": self.request_id,
                "trace_id": self.trace_id,
                "model": self.model.slug,
                "provider": self.model.provider,
                "policy": self.decision.policy,
                "strategy": self.decision.strategy,
                "routing_reason": self.decision.reason,
                "complexity": self.decision.complexity,
                "required_tier": self.decision.required_tier,
                "cache": self.cache_state,
                "cost_usd": self.cost_usd,
                "baseline_cost_usd": self.baseline_cost_usd,
                "saved_usd": self.saved_usd,
                "ttft_ms": round(self.ttft_ms, 2),
                "latency_ms": round(self.latency_ms, 2),
                "gateway_overhead_ms": round(self.overhead_ms, 2),
                "tokens_per_second": round(self.tokens_per_second, 2),
                "attempts": [a.__dict__ for a in self.attempts],
                "guard_flags": self.guard_flags,
            },
        }


class Gateway:
    async def stream(self, ctx: RequestContext) -> AsyncIterator[tuple[str, Any]]:
        """Yield ('meta'|'delta'|'reasoning'|'result', payload) in order."""
        request_id = uuid.uuid4().hex
        started = time.perf_counter()
        overhead_start = started

        async with tracer.span(
            "gateway.request",
            kind="server",
            request_id=request_id,
            trace_id=ctx.trace_id or None,
            parent_id=ctx.parent_span_id,
            route=ctx.route,
            stream=ctx.stream,
            client=ctx.client,
        ) as root:
            trace_id = root.trace_id

            # --- 1. guard -------------------------------------------------
            try:
                guarded = inspect_request(
                    ctx.messages, max_tokens=ctx.max_tokens, redact=ctx.redact
                )
            except GuardRejection as exc:
                root.fail(exc)
                await self._persist_failure(
                    request_id, trace_id, ctx, "guard", str(exc), 400, started
                )
                raise GatewayError(str(exc), status_code=400, reason=f"guard:{exc.rule}") from exc
            root.set(guard_flags=",".join(guarded.flags) or None, redactions=guarded.redactions)

            messages = guarded.messages
            max_tokens = guarded.max_tokens
            prompt_tokens_estimate = estimate_messages_tokens(messages)
            expected_output = min(max_tokens or 512, 1024)

            # --- 2. limits ------------------------------------------------
            key = await self._load_key(ctx.api_key_id)
            scope = ctx.api_key_id or f"anon:{ctx.client}"
            try:
                limiter.check(scope, key, prompt_tokens_estimate + expected_output)
                limiter.check_budget(key)
            except LimitExceeded as exc:
                root.fail(exc)
                await self._persist_failure(
                    request_id, trace_id, ctx, "limited", str(exc), 429, started
                )
                raise GatewayError(str(exc), status_code=429, reason=exc.reason) from exc

            # --- 3. route -------------------------------------------------
            async with tracer.span("route.decide", request_id=request_id) as span:
                try:
                    async with session_scope() as session:
                        decision = await router.decide(
                            session,
                            requested_model=ctx.model,
                            messages=messages,
                            policy_name=ctx.policy,
                            prompt_tokens=prompt_tokens_estimate,
                            expected_output_tokens=expected_output,
                            required_capabilities=ctx.required_capabilities,
                        )
                        baseline = await router.premium_baseline(session)
                except LookupError as exc:
                    span.fail(exc)
                    root.fail(exc)
                    raise GatewayError(str(exc), status_code=503, reason="no_models") from exc
                span.set(
                    model=decision.model.slug,
                    provider=decision.model.provider,
                    policy=decision.policy,
                    strategy=decision.strategy,
                    complexity=decision.complexity,
                    required_tier=decision.required_tier,
                    reason=decision.reason,
                    candidates=len(decision.considered),
                )

            await bus.publish(
                "route.decision",
                {
                    "request_id": request_id,
                    "model": decision.model.slug,
                    "policy": decision.policy,
                    "strategy": decision.strategy,
                    "complexity": decision.complexity,
                    "reason": decision.reason,
                },
            )

            baseline_cost = (
                router.blended_cost(baseline, prompt_tokens_estimate, expected_output)
                if baseline
                else 0.0
            )

            # --- 4. cache -------------------------------------------------
            cache_state = "bypass"
            cache_key = ""
            eligible, cache_reason = response_cache.eligible(ctx.temperature, ctx.cache)
            if eligible:
                cache_key = response_cache.cache_key(
                    messages=messages,
                    scope=f"{decision.policy}:{decision.model.slug}",
                    temperature=ctx.temperature,
                    max_tokens=max_tokens,
                    response_format=ctx.response_format,
                )
                async with tracer.span(
                    "cache.lookup", request_id=request_id, key=cache_key[:16], reason=cache_reason
                ) as span:
                    async with session_scope() as session:
                        entry = await response_cache.lookup(session, cache_key)
                        if entry is not None:
                            hit = {
                                "completion": entry.completion,
                                "prompt_tokens": entry.prompt_tokens,
                                "completion_tokens": entry.completion_tokens,
                                "origin_cost_usd": entry.origin_cost_usd,
                                "hits": entry.hits,
                            }
                        else:
                            hit = None
                    span.set(hit=bool(hit))

                if hit is not None:
                    cache_state = "hit"
                    overhead = (time.perf_counter() - overhead_start) * 1000
                    result = await self._finish_cached(
                        request_id=request_id,
                        trace_id=trace_id,
                        ctx=ctx,
                        decision=decision,
                        hit=hit,
                        baseline_cost=baseline_cost,
                        started=started,
                        overhead_ms=overhead,
                        guard_flags=guarded.flags,
                    )
                    yield "meta", self._meta(result)
                    async for piece in self._replay(result.text):
                        yield "delta", piece
                    yield "result", result
                    return
                cache_state = "miss"
            else:
                root.set(cache_skip_reason=cache_reason)

            # --- 5. attempt chain ----------------------------------------
            call = ChatCall(
                messages=messages,
                temperature=ctx.temperature,
                max_tokens=max_tokens,
                top_p=ctx.top_p,
                stop=ctx.stop,
                presence_penalty=ctx.presence_penalty,
                frequency_penalty=ctx.frequency_penalty,
                response_format=ctx.response_format,
            )

            attempts: list[Attempt] = []
            emitted_meta = False
            text_parts: list[str] = []
            reasoning_parts: list[str] = []
            usage_prompt: int | None = None
            usage_completion: int | None = None
            cached_prompt_tokens = 0
            finish_reason = "stop"
            ttft_ms = 0.0
            upstream_ms = 0.0
            chosen: ModelEntry | None = None
            last_error: Exception | None = None

            waited = await limiter.__aenter__()
            root.set(concurrency_wait_ms=round(waited * 1000, 3))
            try:
                for candidate in decision.chain:
                    allowed, gate_reason = circuits.allows(candidate.provider)
                    if not allowed:
                        attempts.append(
                            Attempt(candidate.slug, candidate.provider, False, 0.0, gate_reason)
                        )
                        continue

                    provider = providers.get(candidate.provider)
                    if provider is None:
                        attempts.append(
                            Attempt(
                                candidate.slug,
                                candidate.provider,
                                False,
                                0.0,
                                "provider not configured",
                            )
                        )
                        continue

                    for attempt_index in range(1, settings.max_attempts + 1):
                        attempt_started = time.perf_counter()
                        first_token_at: float | None = None
                        local_text: list[str] = []
                        local_reasoning: list[str] = []
                        try:
                            async with tracer.span(
                                f"upstream.{candidate.provider}",
                                kind="client",
                                request_id=request_id,
                                model=candidate.slug,
                                upstream_model=candidate.upstream_model,
                                attempt=attempt_index,
                                tier=candidate.tier,
                            ) as span:
                                async for chunk in provider.stream(call, candidate):
                                    if chunk.delta:
                                        if first_token_at is None:
                                            first_token_at = time.perf_counter()
                                            span.event("first_token")
                                            if not emitted_meta:
                                                chosen = candidate
                                                emitted_meta = True
                                                yield (
                                                    "meta",
                                                    {
                                                        "request_id": request_id,
                                                        "trace_id": trace_id,
                                                        "model": candidate.slug,
                                                        "provider": candidate.provider,
                                                        "policy": decision.policy,
                                                        "strategy": decision.strategy,
                                                        "routing_reason": decision.reason,
                                                        "complexity": decision.complexity,
                                                        "cache": cache_state,
                                                    },
                                                )
                                        local_text.append(chunk.delta)
                                        yield "delta", chunk.delta
                                    if chunk.reasoning_delta:
                                        local_reasoning.append(chunk.reasoning_delta)
                                        yield "reasoning", chunk.reasoning_delta
                                    if chunk.prompt_tokens is not None:
                                        usage_prompt = chunk.prompt_tokens
                                    if chunk.completion_tokens is not None:
                                        usage_completion = chunk.completion_tokens
                                    if chunk.cached_prompt_tokens:
                                        cached_prompt_tokens = chunk.cached_prompt_tokens
                                    if chunk.finish_reason:
                                        finish_reason = chunk.finish_reason

                                upstream_ms = (time.perf_counter() - attempt_started) * 1000
                                ttft_ms = (
                                    (first_token_at - attempt_started) * 1000
                                    if first_token_at
                                    else upstream_ms
                                )
                                span.set(
                                    ttft_ms=round(ttft_ms, 2),
                                    duration_ms=round(upstream_ms, 2),
                                    output_chars=sum(len(p) for p in local_text),
                                )

                            circuits.succeeded(candidate.provider)
                            attempts.append(
                                Attempt(candidate.slug, candidate.provider, True, upstream_ms)
                            )
                            text_parts = local_text
                            reasoning_parts = local_reasoning
                            chosen = candidate
                            break

                        except UpstreamError as exc:
                            elapsed = (time.perf_counter() - attempt_started) * 1000
                            last_error = exc
                            circuits.failed(candidate.provider, str(exc))
                            attempts.append(
                                Attempt(
                                    candidate.slug,
                                    candidate.provider,
                                    False,
                                    elapsed,
                                    str(exc)[:300],
                                    exc.retryable,
                                )
                            )
                            if local_text:
                                # Partial output already left the gateway; retrying
                                # would duplicate tokens for the caller.
                                text_parts = local_text
                                chosen = candidate
                                finish_reason = "error"
                                break
                            if not exc.retryable or attempt_index >= settings.max_attempts:
                                break
                            retry_metric.labels(candidate.provider, "retryable").inc()
                            delay = (settings.retry_base_delay_ms / 1000) * (
                                2 ** (attempt_index - 1)
                            )
                            await asyncio.sleep(delay * (0.7 + random.random() * 0.6))
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            elapsed = (time.perf_counter() - attempt_started) * 1000
                            last_error = exc
                            circuits.failed(candidate.provider, str(exc))
                            attempts.append(
                                Attempt(
                                    candidate.slug,
                                    candidate.provider,
                                    False,
                                    elapsed,
                                    f"{exc.__class__.__name__}: {exc}"[:300],
                                )
                            )
                            log.exception("unexpected upstream failure on %s", candidate.slug)
                            break

                    if chosen is not None and text_parts:
                        break
            finally:
                await limiter.__aexit__()

            if chosen is None or not text_parts:
                message = str(last_error) if last_error else "no upstream produced a response"
                root.fail(message)
                await self._persist_failure(
                    request_id,
                    trace_id,
                    ctx,
                    "failed",
                    message,
                    502,
                    started,
                    decision=decision,
                    attempts=attempts,
                )
                raise GatewayError(message, status_code=502, reason="upstream_exhausted")

            # --- 6. account and persist ----------------------------------
            text = "".join(text_parts)
            text, output_flags = scrub_output(text)
            reasoning = "".join(reasoning_parts)
            prompt_tokens = usage_prompt if usage_prompt is not None else prompt_tokens_estimate
            completion_tokens = (
                usage_completion
                if usage_completion is not None
                else estimate_tokens(text + reasoning)
            )
            actual_cost = compute_cost(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                input_price_per_mtok=chosen.input_price_per_mtok,
                output_price_per_mtok=chosen.output_price_per_mtok,
                cached_prompt_tokens=cached_prompt_tokens,
                cached_input_price_per_mtok=chosen.cached_input_price_per_mtok,
            )
            baseline_actual = (
                router.blended_cost(baseline, prompt_tokens, completion_tokens)
                if baseline
                else actual_cost
            )
            saved = max(0.0, round(baseline_actual - actual_cost, 8))

            latency_ms = (time.perf_counter() - started) * 1000
            overhead_ms = max(0.0, latency_ms - upstream_ms)
            generation_seconds = max((upstream_ms - ttft_ms) / 1000, 1e-6)
            tps = completion_tokens / generation_seconds if completion_tokens else 0.0

            result = GatewayResult(
                request_id=request_id,
                trace_id=trace_id,
                model=chosen,
                text=text,
                reasoning=reasoning,
                finish_reason=finish_reason,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cached_prompt_tokens=cached_prompt_tokens,
                cost_usd=actual_cost,
                baseline_cost_usd=baseline_actual,
                saved_usd=saved,
                ttft_ms=ttft_ms,
                latency_ms=latency_ms,
                upstream_ms=upstream_ms,
                overhead_ms=overhead_ms,
                tokens_per_second=tps,
                cache_state=cache_state,
                decision=decision,
                attempts=attempts,
                guard_flags=sorted(set(guarded.flags + output_flags)),
            )

            root.set(
                model=chosen.slug,
                provider=chosen.provider,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=actual_cost,
                saved_usd=saved,
                ttft_ms=round(ttft_ms, 2),
                latency_ms=round(latency_ms, 2),
                overhead_ms=round(overhead_ms, 2),
                tokens_per_second=round(tps, 2),
                cache=cache_state,
            )

            self._observe(result)
            await self._persist(result, ctx, cache_key)
            self._fire_shadow(decision, ctx, request_id, trace_id)

            if not emitted_meta:
                yield "meta", self._meta(result)
            yield "result", result

    # -- non-streaming convenience ---------------------------------------
    async def complete(self, ctx: RequestContext) -> GatewayResult:
        result: GatewayResult | None = None
        async for kind, payload in self.stream(ctx):
            if kind == "result":
                result = payload
        if result is None:  # pragma: no cover - stream always ends with a result
            raise GatewayError("gateway produced no result")
        return result

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _meta(result: GatewayResult) -> dict[str, Any]:
        return {
            "request_id": result.request_id,
            "trace_id": result.trace_id,
            "model": result.model.slug,
            "provider": result.model.provider,
            "policy": result.decision.policy,
            "strategy": result.decision.strategy,
            "routing_reason": result.decision.reason,
            "complexity": result.decision.complexity,
            "cache": result.cache_state,
        }

    @staticmethod
    async def _replay(text: str, group: int = 24) -> AsyncIterator[str]:
        """Re-stream a cached answer so clients see identical mechanics."""
        for index in range(0, len(text), group):
            await asyncio.sleep(0)
            yield text[index : index + group]

    async def _finish_cached(
        self,
        *,
        request_id: str,
        trace_id: str,
        ctx: RequestContext,
        decision: RouteDecision,
        hit: dict[str, Any],
        baseline_cost: float,
        started: float,
        overhead_ms: float,
        guard_flags: list[str],
    ) -> GatewayResult:
        latency_ms = (time.perf_counter() - started) * 1000
        result = GatewayResult(
            request_id=request_id,
            trace_id=trace_id,
            model=decision.model,
            text=hit["completion"],
            reasoning="",
            finish_reason="stop",
            prompt_tokens=int(hit["prompt_tokens"]),
            completion_tokens=int(hit["completion_tokens"]),
            cached_prompt_tokens=int(hit["prompt_tokens"]),
            cost_usd=0.0,
            baseline_cost_usd=max(baseline_cost, float(hit["origin_cost_usd"])),
            saved_usd=round(float(hit["origin_cost_usd"]), 8),
            ttft_ms=latency_ms,
            latency_ms=latency_ms,
            upstream_ms=0.0,
            overhead_ms=overhead_ms,
            tokens_per_second=0.0,
            cache_state="hit",
            decision=decision,
            attempts=[Attempt(decision.model.slug, "cache", True, 0.0)],
            guard_flags=guard_flags,
        )
        self._observe(result)
        await self._persist(result, ctx, "")
        await bus.publish(
            "cache.hit",
            {
                "request_id": request_id,
                "model": decision.model.slug,
                "saved_usd": result.saved_usd,
                "hits": hit["hits"],
            },
        )
        return result

    @staticmethod
    def _observe(result: GatewayResult) -> None:
        slug, provider = result.model.slug, result.model.provider
        inferences.labels(slug, provider, result.cache_state, "ok").inc()
        inference_latency.labels(slug, provider).observe(result.latency_ms / 1000)
        if result.cache_state != "hit":
            ttft_metric.labels(slug, provider).observe(result.ttft_ms / 1000)
            if result.tokens_per_second:
                throughput.labels(slug).observe(result.tokens_per_second)
        token_metric.labels(slug, provider, "input").inc(result.prompt_tokens)
        token_metric.labels(slug, provider, "output").inc(result.completion_tokens)
        cost_metric.labels(slug, provider).inc(result.cost_usd)
        if result.saved_usd:
            savings_metric.labels("cache" if result.cache_state == "hit" else "routing").inc(
                result.saved_usd
            )

    async def _persist(self, result: GatewayResult, ctx: RequestContext, cache_key: str) -> None:
        async with session_scope() as session:
            session.add(
                InferenceRequest(
                    id=result.request_id,
                    trace_id=result.trace_id,
                    api_key_id=ctx.api_key_id,
                    client=ctx.client,
                    route=ctx.route,
                    requested_model=ctx.model or "",
                    resolved_model=result.model.slug,
                    provider=result.model.provider,
                    policy=result.decision.policy,
                    routing_reason=result.decision.reason[:300],
                    complexity=result.decision.complexity,
                    required_tier=result.decision.required_tier,
                    status="ok",
                    http_status=200,
                    attempts=len(result.attempts),
                    stream=ctx.stream,
                    cache_state=result.cache_state,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    total_tokens=result.total_tokens,
                    cost_usd=result.cost_usd,
                    baseline_cost_usd=result.baseline_cost_usd,
                    saved_usd=result.saved_usd,
                    ttft_ms=round(result.ttft_ms, 3),
                    latency_ms=round(result.latency_ms, 3),
                    upstream_ms=round(result.upstream_ms, 3),
                    overhead_ms=round(result.overhead_ms, 3),
                    tokens_per_second=round(result.tokens_per_second, 3),
                    temperature=ctx.temperature,
                    max_tokens=ctx.max_tokens or 0,
                    prompt_hash=cache_key,
                    prompt_preview=_preview(ctx.messages),
                    completion_preview=result.text[:PREVIEW_CHARS],
                    guard_flags=result.guard_flags,
                    meta={
                        "considered": result.decision.considered[:8],
                        "attempts": [a.__dict__ for a in result.attempts],
                        "reasoning_chars": len(result.reasoning),
                    },
                )
            )

            if ctx.api_key_id:
                key = await session.get(ApiKey, ctx.api_key_id)
                if key is not None:
                    key.spent_usd = round(key.spent_usd + result.cost_usd, 8)
                    key.request_count += 1
                    key.token_count += result.total_tokens
                    key.last_used_at = utcnow()

            if cache_key and result.cache_state == "miss" and result.finish_reason == "stop":
                await response_cache.store(
                    session,
                    key=cache_key,
                    model_slug=result.model.slug,
                    provider=result.model.provider,
                    completion=result.text,
                    response={"finish_reason": result.finish_reason},
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    origin_cost_usd=result.cost_usd,
                )

        await bus.publish(
            "request.completed",
            {
                "request_id": result.request_id,
                "trace_id": result.trace_id,
                "model": result.model.slug,
                "provider": result.model.provider,
                "policy": result.decision.policy,
                "cache": result.cache_state,
                "tokens": result.total_tokens,
                "cost_usd": result.cost_usd,
                "saved_usd": result.saved_usd,
                "ttft_ms": round(result.ttft_ms, 1),
                "latency_ms": round(result.latency_ms, 1),
                "tokens_per_second": round(result.tokens_per_second, 1),
            },
        )

    async def _persist_failure(
        self,
        request_id: str,
        trace_id: str,
        ctx: RequestContext,
        status: str,
        error: str,
        http_status: int,
        started: float,
        *,
        decision: RouteDecision | None = None,
        attempts: list[Attempt] | None = None,
    ) -> None:
        latency_ms = (time.perf_counter() - started) * 1000
        model = decision.model.slug if decision else ""
        provider = decision.model.provider if decision else ""
        inferences.labels(model or "-", provider or "-", "miss", status).inc()
        async with session_scope() as session:
            session.add(
                InferenceRequest(
                    id=request_id,
                    trace_id=trace_id,
                    api_key_id=ctx.api_key_id,
                    client=ctx.client,
                    route=ctx.route,
                    requested_model=ctx.model or "",
                    resolved_model=model,
                    provider=provider,
                    policy=decision.policy if decision else (ctx.policy or ""),
                    routing_reason=decision.reason[:300] if decision else "",
                    complexity=decision.complexity if decision else "",
                    status=status,
                    http_status=http_status,
                    error=error[:500],
                    attempts=len(attempts or []) or 1,
                    stream=ctx.stream,
                    cache_state="bypass",
                    latency_ms=round(latency_ms, 3),
                    temperature=ctx.temperature,
                    max_tokens=ctx.max_tokens or 0,
                    prompt_preview=_preview(ctx.messages),
                    meta={"attempts": [a.__dict__ for a in (attempts or [])]},
                )
            )
        await bus.publish(
            "request.failed",
            {
                "request_id": request_id,
                "trace_id": trace_id,
                "status": status,
                "error": error[:200],
                "model": model,
            },
        )

    @staticmethod
    async def _load_key(api_key_id: str | None) -> ApiKey | None:
        if not api_key_id:
            return None
        async with session_scope() as session:
            return await session.scalar(select(ApiKey).where(ApiKey.id == api_key_id))

    def _fire_shadow(
        self,
        decision: RouteDecision,
        ctx: RequestContext,
        parent_id: str,
        trace_id: str,
    ) -> None:
        """Send the same prompt to a comparison model, off the caller's path."""
        if decision.shadow is None:
            return

        async def _run() -> None:
            shadow_ctx = RequestContext(
                messages=ctx.messages,
                model=decision.shadow.slug if decision.shadow else None,
                policy=None,
                temperature=ctx.temperature,
                max_tokens=ctx.max_tokens,
                stream=False,
                cache=False,
                subject=ctx.subject,
                api_key_id=None,
                client=f"shadow:{ctx.client}",
                trace_id=trace_id,
                route="/shadow",
                redact=False,
            )
            with contextlib.suppress(Exception):
                result = await self.complete(shadow_ctx)
                async with session_scope() as session:
                    row = await session.get(InferenceRequest, result.request_id)
                    if row is not None:
                        row.shadow_of = parent_id
                        row.client = f"shadow:{ctx.client}"

        task = asyncio.create_task(_run(), name=f"sentinel-shadow-{parent_id[:8]}")
        _SHADOW_TASKS.add(task)
        task.add_done_callback(_SHADOW_TASKS.discard)


def _preview(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user" and isinstance(message.get("content"), str):
            return message["content"][:PREVIEW_CHARS]
    return ""


_SHADOW_TASKS: set[asyncio.Task[None]] = set()
gateway = Gateway()
