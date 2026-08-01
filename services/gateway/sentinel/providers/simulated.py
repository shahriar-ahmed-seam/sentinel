"""Deterministic local inference engine.

This is not a placeholder for missing functionality. Reproducible, zero-cost
upstreams are what make load testing, CI assertions and a public demo possible:
the concurrency ramp and the tracing-overhead measurement need a backend whose
latency and throughput are known, and no real provider offers that.

Behaviour per catalogue row: `expected_ttft_ms`, `expected_tokens_per_second`
and `simulated_failure_rate` are honoured, so a tier that claims 32 tok/s
actually emits at 32 tok/s.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import re
from collections.abc import AsyncIterator

from ..models import ModelEntry
from ..pricing import classify_prompt, estimate_tokens
from .base import ChatCall, Chunk, UpstreamError

_WORD = re.compile(r"[A-Za-z][A-Za-z'-]+")

OPENERS = {
    1: "Short answer:",
    2: "Here is what matters:",
    3: "Breaking this down:",
    4: "Working through it carefully:",
}

BODIES = {
    1: [
        "the request resolves to a single step, so there is little to add.",
        "no additional context is needed for this one.",
    ],
    2: [
        "the key constraint is {topic}, which sets the shape of the answer.",
        "start from {topic}, then verify the result against the stated inputs.",
        "the trade-off sits between correctness and cost, and {topic} decides it.",
    ],
    3: [
        "first, {topic} determines the boundary conditions.",
        "second, the failure mode to guard against is silent degradation rather than a hard error.",
        "third, measure before optimising: the bottleneck is rarely where intuition puts it.",
        "finally, keep the change reversible so a bad outcome costs minutes, not days.",
    ],
    4: [
        "the problem decomposes into {topic} and the constraints that follow from it.",
        "each branch has a different cost profile, so the decision is economic as much as technical.",
        "the invariant worth preserving is that a partial failure never corrupts committed state.",
        "an explicit budget makes the trade-off visible instead of implicit.",
        "the result should be observable end to end, otherwise regressions surface as anecdotes.",
    ],
}

CLOSERS = {
    1: "",
    2: "That should be enough to proceed.",
    3: "Validate against a held-out example before shipping.",
    4: "Instrument the outcome so the next decision has evidence behind it.",
}


def _topic(prompt: str) -> str:
    words = [w.lower() for w in _WORD.findall(prompt) if len(w) > 4]
    if not words:
        return "the stated requirement"
    seen: list[str] = []
    for word in words:
        if word not in seen:
            seen.append(word)
    return " ".join(seen[:3]) or "the stated requirement"


class SimulatedProvider:
    name = "simulated"
    live = False

    async def stream(self, call: ChatCall, model: ModelEntry) -> AsyncIterator[Chunk]:
        prompt = call.prompt_text
        seed = int(hashlib.sha256((model.slug + prompt).encode()).hexdigest()[:12], 16)
        rng = random.Random(seed)

        if model.simulated_failure_rate > 0 and rng.random() < model.simulated_failure_rate:
            raise UpstreamError(
                f"simulated upstream failure on {model.slug}",
                status_code=503,
                retryable=True,
                provider=self.name,
            )

        _, tier = classify_prompt(call.messages)
        depth = max(1, min(model.tier, 4))
        text = self._compose(prompt, tier, depth, rng)

        budget = call.max_tokens or model.max_output_tokens
        words = text.split()
        # ~0.75 words per token; keep the emitted length inside the caller's cap.
        max_words = max(6, int(budget * 0.75))
        if len(words) > max_words:
            words = words[:max_words]

        ttft = max(0.0, rng.gauss(model.expected_ttft_ms, model.expected_ttft_ms * 0.18)) / 1000
        await asyncio.sleep(ttft)

        rate = max(
            4.0, rng.gauss(model.expected_tokens_per_second, model.expected_tokens_per_second * 0.1)
        )
        # Emit in small groups so streaming looks natural without 1 sleep/token.
        group = max(1, int(rate // 25) + 1)
        per_group = group / rate

        emitted = 0
        for index in range(0, len(words), group):
            piece = " ".join(words[index : index + group])
            prefix = "" if index == 0 else " "
            await asyncio.sleep(per_group)
            emitted += len(piece.split())
            yield Chunk(delta=prefix + piece)

        yield Chunk(
            finish_reason="stop" if len(words) < max_words else "length",
            prompt_tokens=estimate_tokens(prompt),
            completion_tokens=max(1, int(emitted / 0.75)),
        )

    def _compose(self, prompt: str, tier: int, depth: int, rng: random.Random) -> str:
        level = max(1, min(max(tier, depth), 4))
        topic = _topic(prompt)
        lines = [OPENERS[level]]
        pool = BODIES[level]
        count = min(len(pool), 1 + level)
        for body in rng.sample(pool, count):
            lines.append(body.format(topic=topic))
        closer = CLOSERS[level]
        if closer:
            lines.append(closer)
        return " ".join(lines)

    async def close(self) -> None:
        return None
