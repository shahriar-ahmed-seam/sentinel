"""Rate limiting, concurrency admission and budget enforcement.

Token buckets are per process. That is stated rather than hidden: with N
replicas the effective ceiling is N x the configured rate, and the fix is a
shared counter in Redis. For a single-container deployment — and for the load
tests that produce the concurrency numbers — in-process buckets are exact.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from .models import ApiKey
from .observability import inflight, queue_wait, rate_limited
from .settings import settings


class LimitExceeded(Exception):
    def __init__(self, reason: str, message: str, retry_after: float = 1.0) -> None:
        super().__init__(message)
        self.reason = reason
        self.retry_after = retry_after


@dataclass
class Bucket:
    capacity: float
    refill_per_second: float
    tokens: float = field(default=0.0)
    updated: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        self.tokens = self.capacity

    def take(self, amount: float = 1.0) -> tuple[bool, float]:
        now = time.monotonic()
        self.tokens = min(
            self.capacity, self.tokens + (now - self.updated) * self.refill_per_second
        )
        self.updated = now
        if self.tokens >= amount:
            self.tokens -= amount
            return True, 0.0
        deficit = amount - self.tokens
        return False, deficit / max(self.refill_per_second, 1e-9)


class Limiter:
    def __init__(self) -> None:
        self._requests: dict[str, Bucket] = {}
        self._tokens: dict[str, Bucket] = {}
        self._semaphore = asyncio.Semaphore(settings.max_concurrency)
        self._inflight = 0
        self.peak_inflight = 0

    # -- rate ------------------------------------------------------------
    def check(self, scope: str, key: ApiKey | None, estimated_tokens: int) -> None:
        rpm = key.rpm_limit if key else settings.default_rpm_limit
        tpm = key.tpm_limit if key else settings.default_tpm_limit

        request_bucket = self._requests.get(scope)
        if request_bucket is None or request_bucket.capacity != rpm:
            request_bucket = Bucket(capacity=float(rpm), refill_per_second=rpm / 60.0)
            self._requests[scope] = request_bucket

        token_bucket = self._tokens.get(scope)
        if token_bucket is None or token_bucket.capacity != tpm:
            token_bucket = Bucket(capacity=float(tpm), refill_per_second=tpm / 60.0)
            self._tokens[scope] = token_bucket

        allowed, wait = request_bucket.take(1.0)
        if not allowed:
            rate_limited.labels("rpm").inc()
            raise LimitExceeded(
                "rpm", f"Request rate limit reached ({rpm}/min). Retry in {wait:.1f}s.", wait
            )

        allowed, wait = token_bucket.take(float(max(estimated_tokens, 1)))
        if not allowed:
            rate_limited.labels("tpm").inc()
            raise LimitExceeded(
                "tpm", f"Token rate limit reached ({tpm}/min). Retry in {wait:.1f}s.", wait
            )

    @staticmethod
    def check_budget(key: ApiKey | None) -> None:
        if key is None or key.monthly_budget_usd <= 0:
            return
        if key.spent_usd >= key.monthly_budget_usd:
            rate_limited.labels("budget").inc()
            raise LimitExceeded(
                "budget",
                f"Monthly budget of ${key.monthly_budget_usd:.2f} exhausted "
                f"(spent ${key.spent_usd:.4f}).",
                60.0,
            )

    # -- concurrency -----------------------------------------------------
    async def __aenter__(self) -> float:
        started = time.perf_counter()
        await self._semaphore.acquire()
        waited = time.perf_counter() - started
        queue_wait.observe(waited)
        self._inflight += 1
        self.peak_inflight = max(self.peak_inflight, self._inflight)
        inflight.set(self._inflight)
        return waited

    async def __aexit__(self, *_exc: object) -> None:
        self._inflight -= 1
        inflight.set(self._inflight)
        self._semaphore.release()

    @property
    def current_inflight(self) -> int:
        return self._inflight

    def snapshot(self) -> dict[str, object]:
        return {
            "inflight": self._inflight,
            "peak_inflight": self.peak_inflight,
            "max_concurrency": settings.max_concurrency,
            "tracked_scopes": len(self._requests),
            "default_rpm": settings.default_rpm_limit,
            "default_tpm": settings.default_tpm_limit,
            "scope": "per-process (use Redis for a shared ceiling)",
        }


limiter = Limiter()
