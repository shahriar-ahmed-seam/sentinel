export type Tone = "ok" | "warn" | "crit" | "info" | "signal" | "neutral" | "violet";

export type ModelEntry = {
  id: string;
  slug: string;
  display_name: string;
  provider: string;
  upstream_model: string;
  tier: number;
  context_window: number;
  max_output_tokens: number;
  capabilities: string[];
  input_price_per_mtok: number;
  output_price_per_mtok: number;
  cached_input_price_per_mtok: number;
  price_source: string;
  price_verified_at: string | null;
  expected_ttft_ms: number;
  expected_tokens_per_second: number;
  simulated_failure_rate: number;
  enabled: boolean;
  notes: string;
  created_at: string;
};

export type Policy = {
  id: string;
  name: string;
  description: string;
  strategy: "direct" | "cheapest" | "fastest" | "weighted" | "failover" | "quality_tier";
  candidates: string[];
  weights: Record<string, number>;
  fallbacks: string[];
  shadow_model: string;
  shadow_sample_rate: number;
  max_cost_per_1k_tokens: number;
  is_default: boolean;
  enabled: boolean;
  created_at: string;
};

export type InferenceRequestRow = {
  id: string;
  trace_id: string;
  client: string;
  route: string;
  requested_model: string;
  resolved_model: string;
  provider: string;
  policy: string;
  routing_reason: string;
  complexity: string;
  required_tier: number;
  status: string;
  http_status: number;
  error: string;
  attempts: number;
  stream: boolean;
  cache_state: string;
  shadow_of: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number;
  baseline_cost_usd: number;
  saved_usd: number;
  ttft_ms: number;
  latency_ms: number;
  upstream_ms: number;
  overhead_ms: number;
  tokens_per_second: number;
  temperature: number;
  max_tokens: number;
  prompt_preview: string;
  completion_preview: string;
  guard_flags: string[];
  created_at: string;
  meta?: Record<string, unknown>;
  prompt_hash?: string;
};

export type Span = {
  id: string;
  trace_id: string;
  parent_id: string | null;
  request_id: string | null;
  name: string;
  kind: string;
  status: string;
  started_at: string;
  ended_at: string | null;
  duration_ms: number;
  attributes: Record<string, unknown>;
  events: { name: string; at: string; offset_ms: number }[];
};

export type Trace = {
  trace_id: string;
  spans: Span[];
  request: InferenceRequestRow | null;
  total_duration_ms: number;
  span_count: number;
};

export type TraceSummary = {
  trace_id: string;
  request_id: string;
  model: string;
  provider: string;
  status: string;
  cache: string;
  latency_ms: number;
  ttft_ms: number;
  cost_usd: number;
  created_at: string;
};

export type ProviderHealth = {
  provider: string;
  state: "closed" | "open" | "half_open";
  consecutive_failures: number;
  total_failures: number;
  total_requests: number;
  failure_ratio: number;
  last_error: string;
  opened_seconds_ago: number | null;
  configured?: boolean;
};

export type Overview = {
  generated_at: string;
  window_hours: number;
  traffic: {
    requests: number;
    succeeded: number;
    failed: number;
    error_rate: number;
    cache_hits: number;
    cache_hit_rate: number;
    requests_per_minute: number;
  };
  latency: {
    ttft_p50: number;
    ttft_p95: number;
    ttft_p99: number;
    latency_p50: number;
    latency_p95: number;
    latency_p99: number;
    gateway_overhead_p50: number;
    gateway_overhead_p95: number;
  };
  spend: {
    cost_usd: number;
    baseline_usd: number;
    saved_usd: number;
    savings_ratio: number;
    tokens_in: number;
    tokens_out: number;
    cost_per_1k_tokens: number;
  };
  slo: {
    ttft_target_ms: number;
    ttft_attainment: number;
    availability_target: number;
    availability: number;
    error_budget_remaining: number;
  };
  series: {
    t: string;
    requests: number;
    errors: number;
    cache_hits: number;
    cost_usd: number;
    saved_usd: number;
    tokens: number;
    ttft_p50: number;
    ttft_p95: number;
    latency_p95: number;
  }[];
  models: {
    model: string;
    provider: string;
    requests: number;
    share: number;
    cost_usd: number;
    tokens: number;
    ttft_p50: number;
    ttft_p95: number;
    latency_p95: number;
    tokens_per_second: number;
  }[];
  mix: { complexity: Record<string, number>; policy: Record<string, number> };
  providers: ProviderHealth[];
  concurrency: {
    inflight: number;
    peak_inflight: number;
    max_concurrency: number;
    tracked_scopes: number;
    default_rpm: number;
    default_tpm: number;
    scope: string;
  };
  cache: CacheStats;
  tracing: { enabled: boolean; buffered_spans: number; dropped_spans: number };
};

export type CacheStats = {
  entries: number;
  hits: number;
  saved_usd: number;
  cached_completion_tokens: number;
  ttl_seconds: number;
  max_entries: number;
  enabled: boolean;
  max_temperature: number;
};

export type Savings = {
  window_hours: number;
  baseline_model: string | null;
  baseline_usd: number;
  actual_usd: number;
  saved_usd: number;
  saved_ratio: number;
  by_source: { routing: number; cache: number };
  by_model: {
    model: string;
    cache_state: string;
    requests: number;
    cost_usd: number;
    baseline_usd: number;
    saved_usd: number;
  }[];
  method: string;
};

export type RuntimeConfig = {
  cache_enabled: boolean;
  cache_ttl_seconds: number;
  cache_max_temperature: number;
  tracing_enabled: boolean;
  default_rpm_limit: number;
  default_tpm_limit: number;
  max_attempts: number;
  circuit_failure_threshold: number;
  circuit_reset_seconds: number;
  slo_ttft_ms: number;
  slo_availability: number;
  redact_pii: boolean;
};

export type SystemInfo = {
  app: {
    name: string;
    version: string;
    env: string;
    region: string;
    git_sha: string;
    uptime_seconds: number;
  };
  infrastructure: {
    database: string;
    providers_configured: string[];
    live_providers: string[];
    simulate_only: boolean;
    otlp_endpoint: string | null;
    event_subscribers: number;
    event_kinds: string[];
  };
  concurrency: Overview["concurrency"];
  tracing: {
    enabled: boolean;
    buffered_spans: number;
    dropped_spans: number;
    retention_hours: number;
    otlp_mirroring: boolean;
  };
  runtime: RuntimeConfig;
  providers: ProviderHealth[];
  loadtest: { running: boolean; current: string | null };
  limits: {
    max_prompt_chars: number;
    max_output_tokens_cap: number;
    upstream_timeout_seconds: number;
  };
};

export type LoadStage = {
  concurrency: number;
  requests: number;
  completed: number;
  failed: number;
  duration_s: number;
  rps: number;
  ttft_p50: number;
  ttft_p95: number;
  ttft_p99: number;
  latency_p50: number;
  latency_p95: number;
  latency_p99: number;
  overhead_p50: number;
  overhead_p95: number;
  tokens: number;
  cost_usd: number;
  cache_hits: number;
  peak_inflight: number;
  models: Record<string, number>;
  errors: Record<string, number>;
};

export type LoadTest = {
  id: string;
  label: string;
  status: "queued" | "running" | "succeeded" | "failed";
  config: Record<string, unknown>;
  stages: LoadStage[];
  summary: {
    stages?: number;
    requests?: number;
    completed?: number;
    failed?: number;
    error_rate?: number;
    peak_rps?: number;
    peak_rps_concurrency?: number;
    sustained_rps_within_slo?: number | null;
    sustained_concurrency?: number | null;
    slo_ttft_ms?: number;
    tokens?: number;
    cost_usd?: number;
    tracing_overhead?: {
      concurrency: number;
      requests_per_arm: number;
      metric: string;
      overhead_p50_with_tracing_ms: number;
      overhead_p50_without_tracing_ms: number;
      overhead_p95_with_tracing_ms: number;
      overhead_p95_without_tracing_ms: number;
      delta_ms: number;
      overhead_ratio: number;
      latency_p50_with_tracing_ms: number;
      latency_p50_without_tracing_ms: number;
      rps_with_tracing: number;
      rps_without_tracing: number;
      note: string;
    } | null;
  };
  error: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number;
};

export type ApiKey = {
  id: string;
  name: string;
  prefix: string;
  policy: string;
  rpm_limit: number;
  tpm_limit: number;
  monthly_budget_usd: number;
  spent_usd: number;
  request_count: number;
  token_count: number;
  revoked: boolean;
  created_at: string;
  last_used_at: string | null;
  token?: string;
};

export type Alert = {
  id: string;
  level: "info" | "warning" | "critical";
  title: string;
  message: string;
  source: string;
  meta: Record<string, unknown>;
  acknowledged: boolean;
  created_at: string;
};

export type LiveEvent = {
  kind: string;
  at: string;
  data: Record<string, unknown>;
};

export type Explanation = {
  complexity: string;
  required_tier: number;
  prompt_tokens: number;
  expected_output_tokens: number;
  policy: string;
  strategy: string;
  chosen: {
    slug: string;
    provider: string;
    tier: number;
    estimated_cost_usd: number;
    estimated_latency_ms: number;
  };
  reason: string;
  fallbacks: string[];
  shadow: string | null;
  considered: {
    slug: string;
    provider: string;
    tier: number;
    estimated_cost_usd: number;
    estimated_latency_ms: number;
    circuit: string;
    meets_tier: boolean;
  }[];
  baseline: {
    slug: string;
    estimated_cost_usd: number;
    saving_vs_baseline: number;
    saving_ratio: number;
  } | null;
};
