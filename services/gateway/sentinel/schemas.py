"""Request/response contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())


class Plain(BaseModel):
    model_config = ConfigDict(protected_namespaces=())


# --------------------------------------------------------------------------- #
# auth
# --------------------------------------------------------------------------- #
class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    subject: str
    role: str


class ApiKeyCreate(Plain):
    name: str = Field(min_length=2, max_length=80)
    policy: str = ""
    rpm_limit: int = Field(default=240, ge=1, le=100_000)
    tpm_limit: int = Field(default=240_000, ge=100, le=50_000_000)
    monthly_budget_usd: float = Field(default=25.0, ge=0, le=100_000)


class ApiKeyOut(ORMModel):
    id: str
    name: str
    prefix: str
    policy: str
    rpm_limit: int
    tpm_limit: int
    monthly_budget_usd: float
    spent_usd: float
    request_count: int
    token_count: int
    revoked: bool
    created_at: datetime
    last_used_at: datetime | None = None


class ApiKeyCreated(ApiKeyOut):
    token: str


# --------------------------------------------------------------------------- #
# OpenAI-compatible data plane
# --------------------------------------------------------------------------- #
class ChatMessage(Plain):
    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: Any
    name: str | None = None
    tool_call_id: str | None = None


class ChatCompletionRequest(Plain):
    """Accepts the OpenAI shape, plus Sentinel routing extensions."""

    messages: list[ChatMessage] = Field(min_length=1, max_length=200)
    model: str | None = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=32_000)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    stop: list[str] | None = None
    presence_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)
    frequency_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)
    response_format: dict[str, Any] | None = None
    stream: bool = False
    # --- extensions ---
    policy: str | None = Field(default=None, description="Routing policy to apply.")
    cache: bool | None = Field(default=None, description="Force the response cache on or off.")
    capabilities: list[str] = Field(
        default_factory=list, description="Capabilities the chosen model must declare."
    )

    def as_messages(self) -> list[dict[str, Any]]:
        return [m.model_dump(exclude_none=True) for m in self.messages]


class SentinelMeta(Plain):
    request_id: str
    trace_id: str
    provider: str
    policy: str
    strategy: str
    routing_reason: str
    complexity: str
    required_tier: int
    cache: str
    cost_usd: float
    baseline_cost_usd: float
    saved_usd: float
    ttft_ms: float
    latency_ms: float
    gateway_overhead_ms: float
    tokens_per_second: float
    attempts: list[dict[str, Any]]
    guard_flags: list[str]


# --------------------------------------------------------------------------- #
# catalogue and policies
# --------------------------------------------------------------------------- #
class ModelOut(ORMModel):
    id: str
    slug: str
    display_name: str
    provider: str
    upstream_model: str
    tier: int
    context_window: int
    max_output_tokens: int
    capabilities: list[str]
    input_price_per_mtok: float
    output_price_per_mtok: float
    cached_input_price_per_mtok: float
    price_source: str
    price_verified_at: datetime | None = None
    expected_ttft_ms: float
    expected_tokens_per_second: float
    simulated_failure_rate: float
    enabled: bool
    notes: str
    created_at: datetime


class ModelUpdate(Plain):
    display_name: str | None = None
    tier: int | None = Field(default=None, ge=1, le=4)
    enabled: bool | None = None
    input_price_per_mtok: float | None = Field(default=None, ge=0, le=1000)
    output_price_per_mtok: float | None = Field(default=None, ge=0, le=1000)
    cached_input_price_per_mtok: float | None = Field(default=None, ge=0, le=1000)
    expected_ttft_ms: float | None = Field(default=None, ge=0, le=60_000)
    expected_tokens_per_second: float | None = Field(default=None, ge=1, le=5000)
    simulated_failure_rate: float | None = Field(default=None, ge=0, le=1)
    max_output_tokens: int | None = Field(default=None, ge=16, le=32_000)
    capabilities: list[str] | None = None
    notes: str | None = None
    price_source: str | None = None
    mark_price_verified: bool = False


class PolicyOut(ORMModel):
    id: str
    name: str
    description: str
    strategy: str
    candidates: list[str]
    weights: dict[str, Any]
    fallbacks: list[str]
    shadow_model: str
    shadow_sample_rate: float
    max_cost_per_1k_tokens: float
    is_default: bool
    enabled: bool
    created_at: datetime


class PolicyUpsert(Plain):
    name: str = Field(min_length=2, max_length=80)
    description: str = ""
    strategy: Literal["direct", "cheapest", "fastest", "weighted", "failover", "quality_tier"] = (
        "cheapest"
    )
    candidates: list[str] = Field(default_factory=list)
    weights: dict[str, float] = Field(default_factory=dict)
    fallbacks: list[str] = Field(default_factory=list)
    shadow_model: str = ""
    shadow_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    max_cost_per_1k_tokens: float = Field(default=0.0, ge=0.0, le=100.0)
    is_default: bool = False
    enabled: bool = True


# --------------------------------------------------------------------------- #
# traffic and traces
# --------------------------------------------------------------------------- #
class RequestOut(ORMModel):
    id: str
    trace_id: str
    client: str
    route: str
    requested_model: str
    resolved_model: str
    provider: str
    policy: str
    routing_reason: str
    complexity: str
    required_tier: int
    status: str
    http_status: int
    error: str
    attempts: int
    stream: bool
    cache_state: str
    shadow_of: str | None = None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    baseline_cost_usd: float
    saved_usd: float
    ttft_ms: float
    latency_ms: float
    upstream_ms: float
    overhead_ms: float
    tokens_per_second: float
    temperature: float
    max_tokens: int
    prompt_preview: str
    completion_preview: str
    guard_flags: list[str]
    created_at: datetime


class RequestDetail(RequestOut):
    meta: dict[str, Any]
    prompt_hash: str


class SpanOut(ORMModel):
    id: str
    trace_id: str
    parent_id: str | None
    request_id: str | None
    name: str
    kind: str
    status: str
    started_at: datetime
    ended_at: datetime | None
    duration_ms: float
    attributes: dict[str, Any]
    events: list[dict[str, Any]]


class TraceOut(Plain):
    trace_id: str
    spans: list[SpanOut]
    request: RequestDetail | None = None
    total_duration_ms: float
    span_count: int


# --------------------------------------------------------------------------- #
# governance and ops
# --------------------------------------------------------------------------- #
class RuntimeOut(Plain):
    cache_enabled: bool
    cache_ttl_seconds: int
    cache_max_temperature: float
    tracing_enabled: bool
    default_rpm_limit: int
    default_tpm_limit: int
    max_attempts: int
    circuit_failure_threshold: int
    circuit_reset_seconds: int
    slo_ttft_ms: float
    slo_availability: float
    redact_pii: bool


class RuntimeUpdate(Plain):
    cache_enabled: bool | None = None
    cache_ttl_seconds: int | None = Field(default=None, ge=10, le=604_800)
    cache_max_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    tracing_enabled: bool | None = None
    default_rpm_limit: int | None = Field(default=None, ge=1, le=100_000)
    default_tpm_limit: int | None = Field(default=None, ge=100, le=50_000_000)
    max_attempts: int | None = Field(default=None, ge=1, le=6)
    circuit_failure_threshold: int | None = Field(default=None, ge=1, le=100)
    circuit_reset_seconds: int | None = Field(default=None, ge=1, le=3600)
    slo_ttft_ms: float | None = Field(default=None, ge=50, le=60_000)
    slo_availability: float | None = Field(default=None, ge=0.5, le=1.0)
    redact_pii: bool | None = None


class LoadTestRequest(Plain):
    label: str = "concurrency ramp"
    policy: str | None = None
    model: str | None = None
    concurrency_levels: list[int] = Field(default_factory=lambda: [1, 2, 4, 8, 16])
    requests_per_stage: int = Field(default=24, ge=1, le=500)
    max_tokens: int = Field(default=160, ge=16, le=2000)
    measure_tracing_overhead: bool = True


class LoadTestOut(ORMModel):
    id: str
    label: str
    status: str
    config: dict[str, Any]
    stages: list[dict[str, Any]]
    summary: dict[str, Any]
    error: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int


class AlertOut(ORMModel):
    id: str
    level: str
    title: str
    message: str
    source: str
    meta: dict[str, Any]
    acknowledged: bool
    created_at: datetime


class AuditOut(ORMModel):
    id: str
    actor: str
    action: str
    target: str
    meta: dict[str, Any]
    created_at: datetime
