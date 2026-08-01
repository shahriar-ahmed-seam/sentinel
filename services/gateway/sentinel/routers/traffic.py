"""Request log and trace explorer."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import InferenceRequest, Span
from ..schemas import RequestDetail, RequestOut, SpanOut, TraceOut
from ..security import Principal, allow_read

router = APIRouter(prefix="/api", tags=["traffic"])


@router.get("/requests", response_model=list[RequestOut])
async def list_requests(
    model: str | None = None,
    provider: str | None = None,
    policy: str | None = None,
    request_status: str | None = Query(default=None, alias="status"),
    cache: str | None = None,
    include_shadow: bool = False,
    limit: int = Query(default=60, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    _: Principal = Depends(allow_read),
) -> list[InferenceRequest]:
    query = select(InferenceRequest).order_by(InferenceRequest.created_at.desc()).limit(limit)
    if model:
        query = query.where(InferenceRequest.resolved_model == model)
    if provider:
        query = query.where(InferenceRequest.provider == provider)
    if policy:
        query = query.where(InferenceRequest.policy == policy)
    if request_status:
        query = query.where(InferenceRequest.status == request_status)
    if cache:
        query = query.where(InferenceRequest.cache_state == cache)
    if not include_shadow:
        query = query.where(InferenceRequest.shadow_of.is_(None))
    return list((await session.execute(query)).scalars())


@router.get("/requests/{request_id}", response_model=RequestDetail)
async def get_request(
    request_id: str,
    session: AsyncSession = Depends(get_session),
    _: Principal = Depends(allow_read),
) -> InferenceRequest:
    row = await session.get(InferenceRequest, request_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    return row


@router.get("/requests/{request_id}/shadow", response_model=list[RequestOut])
async def shadow_pair(
    request_id: str,
    session: AsyncSession = Depends(get_session),
    _: Principal = Depends(allow_read),
) -> list[InferenceRequest]:
    """The comparison call, if this request had one."""
    rows = await session.execute(
        select(InferenceRequest).where(InferenceRequest.shadow_of == request_id)
    )
    return list(rows.scalars())


@router.get("/traces/{trace_id}", response_model=TraceOut)
async def get_trace(
    trace_id: str,
    session: AsyncSession = Depends(get_session),
    _: Principal = Depends(allow_read),
) -> TraceOut:
    spans = list(
        (
            await session.execute(
                select(Span).where(Span.trace_id == trace_id).order_by(Span.started_at)
            )
        ).scalars()
    )
    if not spans:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trace not found or already pruned")

    request_row = await session.scalar(
        select(InferenceRequest)
        .where(InferenceRequest.trace_id == trace_id)
        .order_by(InferenceRequest.created_at)
        .limit(1)
    )
    total = max((span.duration_ms for span in spans if span.parent_id is None), default=0.0)
    if not total:
        total = max((span.duration_ms for span in spans), default=0.0)

    return TraceOut(
        trace_id=trace_id,
        spans=[SpanOut.model_validate(span) for span in spans],
        request=RequestDetail.model_validate(request_row) if request_row else None,
        total_duration_ms=round(total, 3),
        span_count=len(spans),
    )


@router.get("/traces", response_model=list[dict])
async def recent_traces(
    limit: int = Query(default=30, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    _: Principal = Depends(allow_read),
) -> list[dict]:
    rows = list(
        (
            await session.execute(
                select(InferenceRequest).order_by(InferenceRequest.created_at.desc()).limit(limit)
            )
        ).scalars()
    )
    return [
        {
            "trace_id": row.trace_id,
            "request_id": row.id,
            "model": row.resolved_model,
            "provider": row.provider,
            "status": row.status,
            "cache": row.cache_state,
            "latency_ms": row.latency_ms,
            "ttft_ms": row.ttft_ms,
            "cost_usd": row.cost_usd,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
        if row.trace_id
    ]
