"""Gateway schema: catalogue, policies, requests, spans, cache, keys, budgets."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy import (
    DateTime as SADateTime,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DateTime(TypeDecorator):
    """Always hand back timezone-aware UTC, on Postgres and SQLite alike."""

    impl = SADateTime
    cache_ok = True

    def __init__(self, timezone: bool = True) -> None:
        super().__init__(timezone=timezone)

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(timezone.utc)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )


# --------------------------------------------------------------------------- #
# catalogue
# --------------------------------------------------------------------------- #
class ModelEntry(Base, TimestampMixin):
    """A routable model: provider binding, price book row and capability tier."""

    __tablename__ = "model_catalog"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160), default="")
    provider: Mapped[str] = mapped_column(String(40), index=True)
    upstream_model: Mapped[str] = mapped_column(String(160))
    tier: Mapped[int] = mapped_column(Integer, default=1)  # 1 cheap .. 4 frontier
    context_window: Mapped[int] = mapped_column(Integer, default=32_768)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=4096)
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)

    # Price book, USD per million tokens. Operator-editable: verify against the
    # provider's published pricing before trusting the cost numbers.
    input_price_per_mtok: Mapped[float] = mapped_column(Float, default=0.0)
    output_price_per_mtok: Mapped[float] = mapped_column(Float, default=0.0)
    cached_input_price_per_mtok: Mapped[float] = mapped_column(Float, default=0.0)
    price_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    price_source: Mapped[str] = mapped_column(String(300), default="")

    # Simulated providers use these to model realistic behaviour.
    expected_ttft_ms: Mapped[float] = mapped_column(Float, default=350.0)
    expected_tokens_per_second: Mapped[float] = mapped_column(Float, default=60.0)
    simulated_failure_rate: Mapped[float] = mapped_column(Float, default=0.0)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class RoutingPolicy(Base, TimestampMixin):
    __tablename__ = "routing_policies"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    # direct | cheapest | fastest | weighted | failover | quality_tier
    strategy: Mapped[str] = mapped_column(String(24), default="cheapest")
    candidates: Mapped[list[str]] = mapped_column(JSON, default=list)
    weights: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    fallbacks: Mapped[list[str]] = mapped_column(JSON, default=list)
    shadow_model: Mapped[str] = mapped_column(String(120), default="")
    shadow_sample_rate: Mapped[float] = mapped_column(Float, default=0.0)
    max_cost_per_1k_tokens: Mapped[float] = mapped_column(Float, default=0.0)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


# --------------------------------------------------------------------------- #
# traffic
# --------------------------------------------------------------------------- #
class InferenceRequest(Base):
    __tablename__ = "inference_requests"
    __table_args__ = (
        Index("ix_requests_created_model", "created_at", "resolved_model"),
        Index("ix_requests_trace", "trace_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    trace_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    api_key_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    client: Mapped[str] = mapped_column(String(80), default="anonymous")
    route: Mapped[str] = mapped_column(String(80), default="/v1/chat/completions")

    requested_model: Mapped[str] = mapped_column(String(120), default="")
    resolved_model: Mapped[str] = mapped_column(String(120), default="", index=True)
    provider: Mapped[str] = mapped_column(String(40), default="", index=True)
    policy: Mapped[str] = mapped_column(String(80), default="")
    routing_reason: Mapped[str] = mapped_column(String(300), default="")
    complexity: Mapped[str] = mapped_column(String(24), default="")
    required_tier: Mapped[int] = mapped_column(Integer, default=1)

    status: Mapped[str] = mapped_column(String(24), default="ok", index=True)
    http_status: Mapped[int] = mapped_column(Integer, default=200)
    error: Mapped[str] = mapped_column(String(500), default="")
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    stream: Mapped[bool] = mapped_column(Boolean, default=False)
    cache_state: Mapped[str] = mapped_column(String(16), default="miss")  # hit|miss|bypass|store
    shadow_of: Mapped[str | None] = mapped_column(String(32), nullable=True)

    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    # What the same call would have cost on the most expensive enabled model.
    baseline_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    saved_usd: Mapped[float] = mapped_column(Float, default=0.0)

    ttft_ms: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    upstream_ms: Mapped[float] = mapped_column(Float, default=0.0)
    overhead_ms: Mapped[float] = mapped_column(Float, default=0.0)
    tokens_per_second: Mapped[float] = mapped_column(Float, default=0.0)

    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    max_tokens: Mapped[int] = mapped_column(Integer, default=0)
    prompt_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    prompt_preview: Mapped[str] = mapped_column(Text, default="")
    completion_preview: Mapped[str] = mapped_column(Text, default="")
    guard_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class Span(Base):
    """W3C-compatible span, recorded locally and optionally mirrored to OTLP."""

    __tablename__ = "spans"
    __table_args__ = (Index("ix_spans_trace_start", "trace_id", "started_at"),)

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(32), index=True)
    parent_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(24), default="internal")
    status: Mapped[str] = mapped_column(String(16), default="ok")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    events: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class CacheEntry(Base, TimestampMixin):
    __tablename__ = "cache_entries"
    __table_args__ = (UniqueConstraint("cache_key", name="uq_cache_key"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    cache_key: Mapped[str] = mapped_column(String(64), index=True)
    model_slug: Mapped[str] = mapped_column(String(120), default="")
    provider: Mapped[str] = mapped_column(String(40), default="")
    response: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    completion: Mapped[str] = mapped_column(Text, default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    origin_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    hits: Mapped[int] = mapped_column(Integer, default=0)
    saved_usd: Mapped[float] = mapped_column(Float, default=0.0)
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# --------------------------------------------------------------------------- #
# tenancy, limits, governance
# --------------------------------------------------------------------------- #
class ApiKey(Base, TimestampMixin):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(16), index=True)
    hashed: Mapped[str] = mapped_column(String(128))
    policy: Mapped[str] = mapped_column(String(80), default="")
    rpm_limit: Mapped[int] = mapped_column(Integer, default=240)
    tpm_limit: Mapped[int] = mapped_column(Integer, default=240_000)
    monthly_budget_usd: Mapped[float] = mapped_column(Float, default=25.0)
    spent_usd: Mapped[float] = mapped_column(Float, default=0.0)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProviderHealth(Base):
    __tablename__ = "provider_health"

    provider: Mapped[str] = mapped_column(String(40), primary_key=True)
    state: Mapped[str] = mapped_column(String(16), default="closed")  # closed|open|half_open
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    total_failures: Mapped[int] = mapped_column(Integer, default=0)
    total_requests: Mapped[int] = mapped_column(Integer, default=0)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(String(400), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class LoadTest(Base, TimestampMixin):
    __tablename__ = "load_tests"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    label: Mapped[str] = mapped_column(String(160), default="")
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    stages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)


class Alert(Base, TimestampMixin):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    level: Mapped[str] = mapped_column(String(16), default="info", index=True)
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(60), default="gateway")
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditEvent(Base, TimestampMixin):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    actor: Mapped[str] = mapped_column(String(120), default="system")
    action: Mapped[str] = mapped_column(String(80), index=True)
    target: Mapped[str] = mapped_column(String(200), default="")
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PlatformConfig(Base):
    __tablename__ = "platform_config"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
