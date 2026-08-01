"""Routing: pick a model, then a fallback chain, and explain the choice.

Every decision returns a human-readable reason that is persisted with the
request. A router you cannot interrogate after the fact is a router you cannot
trust with a budget.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import providers
from .circuit import circuits
from .models import ModelEntry, RoutingPolicy
from .pricing import classify_prompt, compute_cost

log = logging.getLogger("sentinel.policy")

STRATEGIES = ("direct", "cheapest", "fastest", "weighted", "failover", "quality_tier")


@dataclass
class RouteDecision:
    model: ModelEntry
    chain: list[ModelEntry]
    policy: str
    strategy: str
    reason: str
    complexity: str
    required_tier: int
    shadow: ModelEntry | None = None
    considered: list[dict[str, Any]] = field(default_factory=list)

    @property
    def fallbacks(self) -> list[ModelEntry]:
        return self.chain[1:]


class Router:
    """Loads catalogue + policies per decision; both are small and cached by PG."""

    async def catalogue(
        self, session: AsyncSession, *, only_enabled: bool = True
    ) -> list[ModelEntry]:
        query = select(ModelEntry).order_by(ModelEntry.tier, ModelEntry.slug)
        if only_enabled:
            query = query.where(ModelEntry.enabled.is_(True))
        rows = list((await session.execute(query)).scalars())
        # A row whose provider has no credentials cannot serve traffic.
        return [row for row in rows if providers.available(row.provider)]

    async def policy(self, session: AsyncSession, name: str | None) -> RoutingPolicy | None:
        if name:
            found = await session.scalar(
                select(RoutingPolicy).where(
                    RoutingPolicy.name == name, RoutingPolicy.enabled.is_(True)
                )
            )
            if found:
                return found
        return await session.scalar(
            select(RoutingPolicy).where(
                RoutingPolicy.is_default.is_(True), RoutingPolicy.enabled.is_(True)
            )
        )

    @staticmethod
    def blended_cost(model: ModelEntry, prompt_tokens: int, output_tokens: int) -> float:
        return compute_cost(
            prompt_tokens=prompt_tokens,
            completion_tokens=output_tokens,
            input_price_per_mtok=model.input_price_per_mtok,
            output_price_per_mtok=model.output_price_per_mtok,
        )

    @staticmethod
    def estimated_latency_ms(model: ModelEntry, output_tokens: int) -> float:
        return (
            model.expected_ttft_ms
            + (output_tokens / max(model.expected_tokens_per_second, 1.0)) * 1000
        )

    async def premium_baseline(self, session: AsyncSession) -> ModelEntry | None:
        """Most expensive enabled model — the counterfactual for savings."""
        rows = await self.catalogue(session)
        if not rows:
            return None
        return max(rows, key=lambda m: m.output_price_per_mtok + m.input_price_per_mtok)

    async def decide(
        self,
        session: AsyncSession,
        *,
        requested_model: str | None,
        messages: list[dict[str, Any]],
        policy_name: str | None,
        prompt_tokens: int,
        expected_output_tokens: int,
        required_capabilities: list[str] | None = None,
    ) -> RouteDecision:
        catalogue = await self.catalogue(session)
        if not catalogue:
            raise LookupError(
                "No routable models. Enable a catalogue entry whose provider has credentials."
            )

        by_slug = {model.slug: model for model in catalogue}
        complexity, required_tier = classify_prompt(messages)
        policy = await self.policy(session, policy_name)

        # 1. An explicit, routable model always wins: callers keep control.
        if requested_model and requested_model in by_slug:
            model = by_slug[requested_model]
            chain = [model, *self._fallback_chain(model, policy, by_slug, [])]
            return RouteDecision(
                model=model,
                chain=chain,
                policy=policy.name if policy else "direct",
                strategy="direct",
                reason=f"caller requested '{requested_model}' explicitly",
                complexity=complexity,
                required_tier=required_tier,
                shadow=self._shadow(policy, by_slug, model),
                considered=[],
            )

        if requested_model and requested_model not in by_slug:
            alias = self._alias(requested_model, catalogue)
            if alias:
                chain = [alias, *self._fallback_chain(alias, policy, by_slug, [])]
                return RouteDecision(
                    model=alias,
                    chain=chain,
                    policy=policy.name if policy else "direct",
                    strategy="direct",
                    reason=(
                        f"'{requested_model}' is not in the catalogue; matched upstream "
                        f"name to '{alias.slug}'"
                    ),
                    complexity=complexity,
                    required_tier=required_tier,
                    shadow=self._shadow(policy, by_slug, alias),
                    considered=[],
                )

        strategy = policy.strategy if policy else "cheapest"
        pool = self._pool(policy, catalogue, by_slug)
        pool = [m for m in pool if self._has_capabilities(m, required_capabilities)]
        if not pool:
            pool = catalogue

        healthy = [m for m in pool if circuits.allows(m.provider)[0]]
        degraded = not healthy
        working = pool if degraded else healthy

        considered = [
            {
                "slug": model.slug,
                "provider": model.provider,
                "tier": model.tier,
                "estimated_cost_usd": round(
                    self.blended_cost(model, prompt_tokens, expected_output_tokens), 8
                ),
                "estimated_latency_ms": round(
                    self.estimated_latency_ms(model, expected_output_tokens), 1
                ),
                "circuit": circuits.get(model.provider).state,
                "meets_tier": model.tier >= required_tier,
            }
            for model in working
        ]

        model, reason = self._select(
            strategy=strategy,
            policy=policy,
            pool=working,
            required_tier=required_tier,
            prompt_tokens=prompt_tokens,
            expected_output_tokens=expected_output_tokens,
        )
        if degraded:
            reason += "; all candidate providers are circuit-limited, proceeding anyway"

        chain = [model, *self._fallback_chain(model, policy, by_slug, working)]
        return RouteDecision(
            model=model,
            chain=chain,
            policy=policy.name if policy else "cheapest",
            strategy=strategy,
            reason=reason,
            complexity=complexity,
            required_tier=required_tier,
            shadow=self._shadow(policy, by_slug, model),
            considered=considered,
        )

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _alias(requested: str, catalogue: list[ModelEntry]) -> ModelEntry | None:
        lowered = requested.lower()
        for model in catalogue:
            if model.upstream_model.lower() == lowered:
                return model
        for model in catalogue:
            if lowered in model.slug.lower() or model.slug.lower() in lowered:
                return model
        return None

    @staticmethod
    def _has_capabilities(model: ModelEntry, required: list[str] | None) -> bool:
        if not required:
            return True
        return set(required).issubset(set(model.capabilities or []))

    @staticmethod
    def _pool(
        policy: RoutingPolicy | None,
        catalogue: list[ModelEntry],
        by_slug: dict[str, ModelEntry],
    ) -> list[ModelEntry]:
        if policy and policy.candidates:
            chosen = [by_slug[slug] for slug in policy.candidates if slug in by_slug]
            if chosen:
                return chosen
        return catalogue

    def _select(
        self,
        *,
        strategy: str,
        policy: RoutingPolicy | None,
        pool: list[ModelEntry],
        required_tier: int,
        prompt_tokens: int,
        expected_output_tokens: int,
    ) -> tuple[ModelEntry, str]:
        capable = [m for m in pool if m.tier >= required_tier] or pool

        if policy and policy.max_cost_per_1k_tokens > 0:
            affordable = [
                m
                for m in capable
                if self.blended_cost(m, 1000, 1000) <= policy.max_cost_per_1k_tokens * 2
            ]
            if affordable:
                capable = affordable

        if strategy == "fastest":
            model = min(capable, key=lambda m: self.estimated_latency_ms(m, expected_output_tokens))
            return model, (
                f"fastest capable model for a '{required_tier}'-tier prompt: "
                f"~{self.estimated_latency_ms(model, expected_output_tokens):.0f}ms estimated"
            )

        if strategy == "weighted" and policy and policy.weights:
            weighted = [(m, float(policy.weights.get(m.slug, 0) or 0)) for m in capable]
            weighted = [(m, w) for m, w in weighted if w > 0]
            if weighted:
                total = sum(w for _, w in weighted)
                pick = random.uniform(0, total)
                cursor = 0.0
                for model, weight in weighted:
                    cursor += weight
                    if pick <= cursor:
                        return model, (
                            f"weighted split: {model.slug} at " f"{weight / total:.0%} of traffic"
                        )

        if strategy == "failover" and policy and policy.candidates:
            for slug in policy.candidates:
                for model in capable:
                    if model.slug == slug:
                        return model, f"failover order: first healthy candidate is {slug}"

        if strategy == "quality_tier":
            model = min(
                (m for m in capable if m.tier >= required_tier),
                key=lambda m: (m.tier, self.blended_cost(m, prompt_tokens, expected_output_tokens)),
                default=capable[0],
            )
            return model, (
                f"lowest tier that still satisfies a '{required_tier}'-tier prompt: "
                f"tier {model.tier}"
            )

        # default: cheapest capable
        model = min(
            capable, key=lambda m: self.blended_cost(m, prompt_tokens, expected_output_tokens)
        )
        cost = self.blended_cost(model, prompt_tokens, expected_output_tokens)
        return model, (
            f"cheapest model at or above tier {required_tier} "
            f"(estimated ${cost:.6f} for ~{prompt_tokens}+{expected_output_tokens} tokens)"
        )

    @staticmethod
    def _fallback_chain(
        primary: ModelEntry,
        policy: RoutingPolicy | None,
        by_slug: dict[str, ModelEntry],
        pool: list[ModelEntry],
    ) -> list[ModelEntry]:
        chain: list[ModelEntry] = []
        if policy:
            for slug in policy.fallbacks or []:
                model = by_slug.get(slug)
                if model and model.slug != primary.slug:
                    chain.append(model)
        if not chain:
            # Implicit fallback: a different provider at a comparable tier.
            for model in sorted(pool, key=lambda m: abs(m.tier - primary.tier)):
                if model.provider != primary.provider and model.slug != primary.slug:
                    chain.append(model)
                    break
        return chain[:3]

    @staticmethod
    def _shadow(
        policy: RoutingPolicy | None,
        by_slug: dict[str, ModelEntry],
        chosen: ModelEntry,
    ) -> ModelEntry | None:
        if not policy or not policy.shadow_model or policy.shadow_sample_rate <= 0:
            return None
        if random.random() > policy.shadow_sample_rate:
            return None
        shadow = by_slug.get(policy.shadow_model)
        if shadow is None or shadow.slug == chosen.slug:
            return None
        return shadow


router = Router()


def seed_policies() -> list[dict[str, Any]]:
    return [
        {
            "name": "cost-optimised",
            "description": (
                "Classify the prompt, then send it to the cheapest model that can handle "
                "it. The default: it is where the savings number comes from."
            ),
            "strategy": "cheapest",
            "candidates": ["sim-nano", "sim-small", "sim-large", "deepseek-chat"],
            "fallbacks": ["sim-small", "sim-large"],
            "shadow_model": "sim-large",
            "shadow_sample_rate": 0.15,
            "is_default": True,
        },
        {
            "name": "latency-first",
            "description": "Lowest estimated time-to-completion among capable models.",
            "strategy": "fastest",
            "candidates": ["sim-nano", "sim-small", "sim-large"],
            "fallbacks": ["sim-small"],
        },
        {
            "name": "ab-split",
            "description": "Weighted A/B between two tiers for quality comparison.",
            "strategy": "weighted",
            "candidates": ["sim-small", "sim-large"],
            "weights": {"sim-small": 80, "sim-large": 20},
            "fallbacks": ["sim-nano"],
        },
        {
            "name": "premium-only",
            "description": "Always the frontier tier. The cost baseline to beat.",
            "strategy": "failover",
            "candidates": ["sim-frontier", "sim-large"],
            "fallbacks": ["sim-large"],
        },
        {
            "name": "live-upstream",
            "description": "Prefer a real provider, fall back to simulated tiers.",
            "strategy": "failover",
            "candidates": ["deepseek-chat", "deepseek-reasoner", "sim-large"],
            "fallbacks": ["sim-large", "sim-small"],
        },
    ]
