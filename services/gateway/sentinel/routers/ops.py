"""Operational controls: runtime policy, cache, circuits, load tests, alerts."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import cache as response_cache
from ..circuit import circuits
from ..db import get_session
from ..events import record_audit
from ..limits import limiter
from ..loadtest import load_tester
from ..models import Alert, AuditEvent, LoadTest
from ..runtime import config as runtime_config
from ..runtime import save as save_runtime
from ..schemas import (
    AlertOut,
    AuditOut,
    LoadTestOut,
    LoadTestRequest,
    RuntimeOut,
    RuntimeUpdate,
)
from ..security import Principal, allow_read, require_operator

router = APIRouter(prefix="/api", tags=["ops"])


# --------------------------------------------------------------------------- #
# runtime policy
# --------------------------------------------------------------------------- #
@router.get("/runtime", response_model=RuntimeOut)
async def get_runtime(_: Principal = Depends(allow_read)) -> dict[str, Any]:
    return runtime_config.as_dict()


@router.put("/runtime", response_model=RuntimeOut)
async def update_runtime(
    payload: RuntimeUpdate,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> dict[str, Any]:
    updates = payload.model_dump(exclude_none=True)
    if updates:
        await save_runtime(session, updates)
        await record_audit(session, actor=principal.subject, action="runtime.update", meta=updates)
        await session.commit()
    return runtime_config.as_dict()


# --------------------------------------------------------------------------- #
# cache
# --------------------------------------------------------------------------- #
@router.get("/cache")
async def cache_stats(
    session: AsyncSession = Depends(get_session),
    _: Principal = Depends(allow_read),
) -> dict[str, Any]:
    return await response_cache.stats(session)


@router.delete("/cache")
async def purge_cache(
    expired_only: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> dict[str, Any]:
    removed = await response_cache.purge(session, expired_only=expired_only)
    await record_audit(
        session,
        actor=principal.subject,
        action="cache.purge",
        meta={"removed": removed, "expired_only": expired_only},
    )
    await session.commit()
    return {"removed": removed, "expired_only": expired_only}


# --------------------------------------------------------------------------- #
# providers / circuits
# --------------------------------------------------------------------------- #
@router.get("/providers")
async def provider_health(_: Principal = Depends(allow_read)) -> dict[str, Any]:
    from .. import providers as provider_registry

    return {
        "providers": [
            {
                **snapshot,
                "configured": provider_registry.available(str(snapshot["provider"])),
            }
            for snapshot in circuits.all()
        ],
        "configured": sorted(provider_registry.registry()),
        "concurrency": limiter.snapshot(),
    }


@router.post("/providers/{provider}/reset")
async def reset_circuit(
    provider: str,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> dict[str, Any]:
    circuits.reset(provider)
    await record_audit(session, actor=principal.subject, action="circuit.reset", target=provider)
    await session.commit()
    return {"provider": provider, "state": "closed"}


# --------------------------------------------------------------------------- #
# load tests
# --------------------------------------------------------------------------- #
@router.get("/loadtests", response_model=list[LoadTestOut])
async def list_loadtests(
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    _: Principal = Depends(allow_read),
) -> list[LoadTest]:
    rows = await session.execute(select(LoadTest).order_by(LoadTest.created_at.desc()).limit(limit))
    return list(rows.scalars())


@router.get("/loadtests/{test_id}", response_model=LoadTestOut)
async def get_loadtest(
    test_id: str,
    session: AsyncSession = Depends(get_session),
    _: Principal = Depends(allow_read),
) -> LoadTest:
    row = await session.get(LoadTest, test_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Load test not found")
    return row


@router.post("/loadtests", response_model=LoadTestOut, status_code=status.HTTP_202_ACCEPTED)
async def submit_loadtest(
    payload: LoadTestRequest,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> LoadTest:
    levels = sorted({max(1, min(level, 256)) for level in payload.concurrency_levels})[:8]
    if not levels:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No concurrency levels given")
    try:
        test_id = await load_tester.submit(
            label=payload.label,
            policy=payload.policy,
            model=payload.model,
            concurrency_levels=levels,
            requests_per_stage=payload.requests_per_stage,
            max_tokens=payload.max_tokens,
            measure_tracing_overhead=payload.measure_tracing_overhead,
            actor=principal.subject,
        )
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    await record_audit(
        session,
        actor=principal.subject,
        action="loadtest.submit",
        target=test_id,
        meta={"levels": levels, "requests_per_stage": payload.requests_per_stage},
    )
    await session.commit()
    row = await session.get(LoadTest, test_id)
    if row is None:  # pragma: no cover
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Load test vanished")
    return row


# --------------------------------------------------------------------------- #
# alerts and audit
# --------------------------------------------------------------------------- #
@router.get("/alerts", response_model=list[AlertOut])
async def list_alerts(
    limit: int = Query(default=40, ge=1, le=200),
    unacknowledged: bool = False,
    session: AsyncSession = Depends(get_session),
    _: Principal = Depends(allow_read),
) -> list[Alert]:
    query = select(Alert).order_by(Alert.created_at.desc()).limit(limit)
    if unacknowledged:
        query = query.where(Alert.acknowledged.is_(False))
    return list((await session.execute(query)).scalars())


@router.post("/alerts/{alert_id}/ack", response_model=AlertOut)
async def acknowledge(
    alert_id: str,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> Alert:
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    alert.acknowledged = True
    await record_audit(
        session, actor=principal.subject, action="alert.ack", target=alert.title[:120]
    )
    await session.commit()
    return alert


@router.get("/audit", response_model=list[AuditOut])
async def audit_log(
    limit: int = Query(default=60, ge=1, le=300),
    session: AsyncSession = Depends(get_session),
    _: Principal = Depends(allow_read),
) -> list[AuditEvent]:
    rows = await session.execute(
        select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)
    )
    return list(rows.scalars())
