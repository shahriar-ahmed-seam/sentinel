"""Model catalogue (price book) and routing policies."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import providers
from ..db import get_session
from ..events import bus, record_audit
from ..models import ModelEntry, RoutingPolicy, utcnow
from ..policy import STRATEGIES
from ..policy import router as route_engine
from ..pricing import classify_prompt
from ..schemas import ModelOut, ModelUpdate, PolicyOut, PolicyUpsert
from ..security import Principal, allow_read, require_operator

router = APIRouter(prefix="/api", tags=["catalog"])


# --------------------------------------------------------------------------- #
# models
# --------------------------------------------------------------------------- #
@router.get("/models", response_model=list[ModelOut])
async def list_models(
    session: AsyncSession = Depends(get_session),
    _: Principal = Depends(allow_read),
) -> list[ModelEntry]:
    rows = await session.execute(select(ModelEntry).order_by(ModelEntry.tier, ModelEntry.slug))
    return list(rows.scalars())


@router.get("/models/routable")
async def routable(
    session: AsyncSession = Depends(get_session),
    _: Principal = Depends(allow_read),
) -> dict[str, Any]:
    """What the router can actually pick right now, and why."""
    rows = list((await session.execute(select(ModelEntry))).scalars())
    return {
        "providers": {
            name: {"live": getattr(provider, "live", False)}
            for name, provider in providers.registry().items()
        },
        "models": [
            {
                "slug": row.slug,
                "provider": row.provider,
                "tier": row.tier,
                "enabled": row.enabled,
                "provider_configured": providers.available(row.provider),
                "routable": row.enabled and providers.available(row.provider),
                "blocked_reason": (
                    ""
                    if row.enabled and providers.available(row.provider)
                    else (
                        "disabled in catalogue"
                        if not row.enabled
                        else "provider has no credentials"
                    )
                ),
            }
            for row in rows
        ],
    }


@router.patch("/models/{slug}", response_model=ModelOut)
async def update_model(
    slug: str,
    payload: ModelUpdate,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> ModelEntry:
    model = await session.scalar(select(ModelEntry).where(ModelEntry.slug == slug))
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Model not in catalogue")

    changes = payload.model_dump(exclude_none=True, exclude={"mark_price_verified"})
    for field, value in changes.items():
        setattr(model, field, value)
    if payload.mark_price_verified:
        model.price_verified_at = utcnow()

    await record_audit(
        session,
        actor=principal.subject,
        action="catalog.update",
        target=slug,
        meta=changes,
    )
    await session.commit()
    await bus.publish("catalog.changed", {"slug": slug, "fields": sorted(changes)})
    return model


# --------------------------------------------------------------------------- #
# policies
# --------------------------------------------------------------------------- #
@router.get("/policies", response_model=list[PolicyOut])
async def list_policies(
    session: AsyncSession = Depends(get_session),
    _: Principal = Depends(allow_read),
) -> list[RoutingPolicy]:
    rows = await session.execute(select(RoutingPolicy).order_by(RoutingPolicy.name))
    return list(rows.scalars())


@router.get("/policies/strategies")
async def strategies(_: Principal = Depends(allow_read)) -> dict[str, Any]:
    return {
        "strategies": [
            {"name": "direct", "detail": "Use the model the caller asked for."},
            {"name": "cheapest", "detail": "Cheapest model at or above the required tier."},
            {"name": "fastest", "detail": "Lowest estimated time to completion."},
            {"name": "weighted", "detail": "Weighted split for A/B comparison."},
            {"name": "failover", "detail": "Ordered preference, first healthy candidate wins."},
            {"name": "quality_tier", "detail": "Lowest tier that satisfies the prompt."},
        ],
        "known": list(STRATEGIES),
    }


@router.put("/policies/{name}", response_model=PolicyOut)
async def upsert_policy(
    name: str,
    payload: PolicyUpsert,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> RoutingPolicy:
    policy = await session.scalar(select(RoutingPolicy).where(RoutingPolicy.name == name))
    fields = payload.model_dump()
    fields["name"] = name

    if policy is None:
        policy = RoutingPolicy(**fields)
        session.add(policy)
        action = "policy.create"
    else:
        for field, value in fields.items():
            setattr(policy, field, value)
        action = "policy.update"

    await session.flush()
    if payload.is_default:
        await session.execute(
            update(RoutingPolicy).where(RoutingPolicy.id != policy.id).values(is_default=False)
        )
    await record_audit(session, actor=principal.subject, action=action, target=name)
    await session.commit()
    await bus.publish("policy.changed", {"name": name, "strategy": payload.strategy})
    return policy


@router.post("/policies/{name}/default", response_model=PolicyOut)
async def set_default(
    name: str,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> RoutingPolicy:
    policy = await session.scalar(select(RoutingPolicy).where(RoutingPolicy.name == name))
    if policy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Policy not found")
    await session.execute(update(RoutingPolicy).values(is_default=False))
    policy.is_default = True
    policy.enabled = True
    await record_audit(session, actor=principal.subject, action="policy.default", target=name)
    await session.commit()
    await bus.publish("policy.changed", {"name": name, "default": True})
    return policy


@router.delete("/policies/{name}")
async def delete_policy(
    name: str,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> dict[str, str]:
    policy = await session.scalar(select(RoutingPolicy).where(RoutingPolicy.name == name))
    if policy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Policy not found")
    if policy.is_default:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot delete the default policy")
    await session.delete(policy)
    await record_audit(session, actor=principal.subject, action="policy.delete", target=name)
    await session.commit()
    return {"deleted": name}


# --------------------------------------------------------------------------- #
# routing explainer
# --------------------------------------------------------------------------- #
@router.post("/policies/explain")
async def explain(
    body: dict[str, Any],
    session: AsyncSession = Depends(get_session),
    _: Principal = Depends(allow_read),
) -> dict[str, Any]:
    """Dry-run the router: which model would this prompt get, and why?

    No upstream is called and nothing is billed, which makes it safe to expose
    read-only and genuinely useful for tuning a policy.
    """
    prompt = str(body.get("prompt") or "")
    messages = body.get("messages") or [{"role": "user", "content": prompt}]
    policy_name = body.get("policy")
    expected_output = int(body.get("expected_output_tokens") or 400)

    from ..pricing import estimate_messages_tokens

    prompt_tokens = estimate_messages_tokens(messages)
    complexity, tier = classify_prompt(messages)

    try:
        decision = await route_engine.decide(
            session,
            requested_model=body.get("model"),
            messages=messages,
            policy_name=policy_name,
            prompt_tokens=prompt_tokens,
            expected_output_tokens=expected_output,
            required_capabilities=body.get("capabilities") or [],
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    baseline = await route_engine.premium_baseline(session)
    chosen_cost = route_engine.blended_cost(decision.model, prompt_tokens, expected_output)
    baseline_cost = (
        route_engine.blended_cost(baseline, prompt_tokens, expected_output) if baseline else 0.0
    )

    return {
        "complexity": complexity,
        "required_tier": tier,
        "prompt_tokens": prompt_tokens,
        "expected_output_tokens": expected_output,
        "policy": decision.policy,
        "strategy": decision.strategy,
        "chosen": {
            "slug": decision.model.slug,
            "provider": decision.model.provider,
            "tier": decision.model.tier,
            "estimated_cost_usd": round(chosen_cost, 8),
            "estimated_latency_ms": round(
                route_engine.estimated_latency_ms(decision.model, expected_output), 1
            ),
        },
        "reason": decision.reason,
        "fallbacks": [m.slug for m in decision.fallbacks],
        "shadow": decision.shadow.slug if decision.shadow else None,
        "considered": decision.considered,
        "baseline": (
            {
                "slug": baseline.slug,
                "estimated_cost_usd": round(baseline_cost, 8),
                "saving_vs_baseline": round(max(0.0, baseline_cost - chosen_cost), 8),
                "saving_ratio": round(max(0.0, baseline_cost - chosen_cost) / baseline_cost, 4)
                if baseline_cost
                else 0.0,
            }
            if baseline
            else None
        ),
    }
