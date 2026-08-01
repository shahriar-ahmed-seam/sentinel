"""Per-provider circuit breaker.

State lives in memory for the hot path and is mirrored to `provider_health` so
the console and Prometheus can see it. In a multi-replica deployment each
replica trips independently, which is the conservative behaviour: a replica that
cannot reach an upstream should stop sending it traffic regardless of what its
peers observe.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from .events import bus
from .observability import circuit_state
from .settings import settings

log = logging.getLogger("sentinel.circuit")

CLOSED, OPEN, HALF_OPEN = "closed", "open", "half_open"
_STATE_VALUE = {CLOSED: 0.0, HALF_OPEN: 1.0, OPEN: 2.0}


@dataclass
class Breaker:
    provider: str
    state: str = CLOSED
    consecutive_failures: int = 0
    total_failures: int = 0
    total_requests: int = 0
    opened_at: float = 0.0
    half_open_probes: int = 0
    last_error: str = ""
    history: list[dict[str, object]] = field(default_factory=list)

    def snapshot(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "state": self.state,
            "consecutive_failures": self.consecutive_failures,
            "total_failures": self.total_failures,
            "total_requests": self.total_requests,
            "failure_ratio": round(self.total_failures / max(self.total_requests, 1), 4),
            "last_error": self.last_error,
            "opened_seconds_ago": round(time.monotonic() - self.opened_at, 1)
            if self.opened_at
            else None,
        }


class CircuitRegistry:
    def __init__(self) -> None:
        self._breakers: dict[str, Breaker] = {}

    def get(self, provider: str) -> Breaker:
        breaker = self._breakers.get(provider)
        if breaker is None:
            breaker = Breaker(provider=provider)
            self._breakers[provider] = breaker
            circuit_state.labels(provider).set(0)
        return breaker

    def all(self) -> list[dict[str, object]]:
        return [breaker.snapshot() for breaker in self._breakers.values()]

    # -- gate ------------------------------------------------------------
    def allows(self, provider: str) -> tuple[bool, str]:
        breaker = self.get(provider)
        if breaker.state == CLOSED:
            return True, ""
        if breaker.state == OPEN:
            elapsed = time.monotonic() - breaker.opened_at
            if elapsed < settings.circuit_reset_seconds:
                return (
                    False,
                    f"circuit open for {provider} "
                    f"({settings.circuit_reset_seconds - elapsed:.0f}s to probe)",
                )
            self._transition(breaker, HALF_OPEN)
            breaker.half_open_probes = 0
        if breaker.state == HALF_OPEN:
            if breaker.half_open_probes >= settings.circuit_half_open_probes:
                return False, f"circuit half-open for {provider}, probe budget spent"
            breaker.half_open_probes += 1
        return True, ""

    # -- outcomes --------------------------------------------------------
    def succeeded(self, provider: str) -> None:
        breaker = self.get(provider)
        breaker.total_requests += 1
        breaker.consecutive_failures = 0
        if breaker.state != CLOSED:
            self._transition(breaker, CLOSED)
            breaker.opened_at = 0.0
            breaker.half_open_probes = 0

    def failed(self, provider: str, error: str) -> None:
        breaker = self.get(provider)
        breaker.total_requests += 1
        breaker.total_failures += 1
        breaker.consecutive_failures += 1
        breaker.last_error = error[:400]
        if breaker.state == HALF_OPEN:
            self._transition(breaker, OPEN)
            breaker.opened_at = time.monotonic()
            return
        if breaker.consecutive_failures >= settings.circuit_failure_threshold:
            self._transition(breaker, OPEN)
            breaker.opened_at = time.monotonic()

    def reset(self, provider: str) -> None:
        breaker = self.get(provider)
        breaker.consecutive_failures = 0
        breaker.half_open_probes = 0
        breaker.opened_at = 0.0
        self._transition(breaker, CLOSED)

    def _transition(self, breaker: Breaker, state: str) -> None:
        if breaker.state == state:
            return
        previous, breaker.state = breaker.state, state
        circuit_state.labels(breaker.provider).set(_STATE_VALUE[state])
        breaker.history.insert(
            0, {"from": previous, "to": state, "at": time.time(), "error": breaker.last_error}
        )
        del breaker.history[12:]
        log.warning("circuit %s: %s -> %s", breaker.provider, previous, state)
        bus.publish_soon(
            "circuit.changed",
            {
                "provider": breaker.provider,
                "from": previous,
                "to": state,
                "error": breaker.last_error,
            },
        )


circuits = CircuitRegistry()
