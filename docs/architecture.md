# Architecture

Sentinel is a model-serving gateway. It terminates an OpenAI-compatible API,
decides which model should answer, enforces limits and budgets, absorbs upstream
failure, and accounts for and traces everything it does.

---

## 1. System shape

```
   OpenAI SDK / curl / your services ─────────┐
                                              │  POST /v1/chat/completions
   browser ──▶ Console (Next.js 16) ──────────┤  (streaming SSE supported)
               overview · requests · traces   │
               routing · catalogue            │
               playground · load · settings   │
                                              ▼
   ┌──────────────────────────────────────────────────────────────────────┐
   │  Gateway (FastAPI, async)                                            │
   │                                                                      │
   │   guard ─▶ limits ─▶ route ─▶ cache ─▶ attempt chain ─▶ account      │
   │     │        │         │        │           │              │         │
   │     │        │         │        │           │              └─ persist│
   │     └────────┴─────────┴────────┴───────────┴──── every step a span  │
   ├──────────────────────────────────────────────────────────────────────┤
   │  Control plane /api   requests · traces · policies · catalogue ·     │
   │                       keys · runtime · cache · providers · loadtests │
   │  /metrics Prometheus  /api/stream server-sent events                 │
   ├──────────────────────────────────────────────────────────────────────┤
   │  Upstreams   deepseek │ openai │ any OpenAI-compatible │ local engine│
   │  State       postgres or sqlite · span store · in-process bus        │
   └──────────────────────────────────────────────────────────────────────┘
                                    │ optional
                                    ▼
                         OTLP collector ─▶ Jaeger / Tempo
```

| Plane | Prefix | Auth |
| --- | --- | --- |
| Data | `/v1/*` | Hashed service key (`sk-sent-…`), operator JWT, or anonymous when explicitly allowed |
| Control | `/api/*` | Operator JWT; `GET` optionally public |

---

## 2. The request pipeline

Every call takes one path. Each stage is a span, so a trace answers "where did
the time go and why did it cost that?" without adding logging.

**Guard.** Prompt size ceiling, output-token clamp, and redaction of emails,
phone numbers, card-like digit runs and credential patterns (`sk-`, `ghp_`,
`AKIA…`, Google and Slack shapes). Output is scrubbed for credentials on the way
back, because an upstream echoing a leaked key is a real failure mode. This is
hygiene, not content safety — the module does not pretend otherwise.

**Limits.** Two token buckets per scope (requests/minute and tokens/minute) plus
a monthly budget check against the key's attributed spend, then a concurrency
semaphore. The wait for a slot is recorded, which is what separates "the model is
slow" from "we are queueing".

**Route.** A rule-based classifier scores the prompt into `trivial | standard |
complex | frontier` from length, code markers and reasoning verbs. The policy
then selects from its candidate set:

| Strategy | Selection |
| --- | --- |
| `direct` | The caller's explicit model, always honoured |
| `cheapest` | Lowest blended cost at or above the required tier |
| `fastest` | Lowest `ttft + tokens / throughput` estimate |
| `weighted` | Weighted random split, for A/B comparison |
| `failover` | Ordered preference, first healthy candidate |
| `quality_tier` | Lowest tier that still satisfies the prompt |

Candidates whose provider has an open circuit are filtered out; if that empties
the pool the gateway proceeds anyway and says so in the reason string. The full
candidate set with per-candidate cost and latency estimates is stored on the
request, so a routing decision is auditable months later.

Classification is deliberately not an LLM call. Paying a model to decide which
model to pay is a poor trade on the hot path, and a rule you can read is a rule
you can defend to whoever owns the budget.

**Cache.** SHA-256 over a canonical form of the messages plus the parameters that
change the answer (model scope, temperature, max tokens, response format). Only
calls at or below the temperature ceiling qualify unless the caller passes
`cache: true`; caching a temperature-0.9 brainstorm would be wrong. A hit costs
nothing, is re-streamed to the client so mechanics look identical, and is
credited with the full cost of the call it replaced.

**Attempt chain.** For each candidate: check the circuit, then up to
`max_attempts` tries with exponentially backed-off, jittered delays on retryable
failures (timeouts, transport errors, 408/409/425/429/5xx). Non-retryable errors
move to the next candidate immediately. If tokens have already been streamed to
the client the gateway stops rather than retrying, because duplicating output is
worse than a truncated answer.

**Account.** Token counts come from the provider when reported and from a
documented heuristic when not. Cost is computed from the catalogue's price book,
including the reduced rate for provider-side prompt-cache hits. The same tokens
are then priced against the most expensive enabled model — the premium baseline —
and the difference is recorded as avoided spend.

---

## 3. Circuit breakers

State is per process, per provider:

```
closed ──(N consecutive failures)──▶ open ──(cooldown elapsed)──▶ half_open
   ▲                                                                  │
   └──────────────── success ◀── limited probe budget ────────────────┘
```

The breaker is scoped to the **provider**, not the model. A single broken model
served by a healthy provider is a routing problem, handled by failover; the
breaker exists to stop hammering an endpoint that is actually down. A consequence
worth knowing: successes on a healthy model keep that provider's circuit closed
even while another of its models fails every call. That is the correct verdict —
the provider is reachable — and `scripts/demo.py` demonstrates exactly this case
rather than glossing over it.

Each replica trips independently. That is the conservative choice: a replica that
cannot reach an upstream should stop sending it traffic regardless of what its
peers observe.

---

## 4. Tracing

Spans use W3C-format ids (16-byte trace, 8-byte span) and an inbound
`traceparent` header is honoured, so a caller's trace continues through the
gateway into the upstream span. Spans are buffered in memory and flushed in
batches off the request path; the flush duration is itself a Prometheus
histogram, so the cost of observability is observable.

Two sinks, independently useful:

1. **Local store** — always on. Powers the built-in waterfall viewer, which needs
   no collector to operate. Pruned on a retention window by a background janitor.
2. **OTLP/HTTP** — enabled by setting `OTEL_EXPORTER_OTLP_ENDPOINT` with the
   optional OpenTelemetry SDK installed. If the import fails the gateway logs a
   warning and carries on locally rather than refusing to start.

The load test quantifies the overhead by running the same stage with recording on
and off and comparing **gateway overhead** (total latency minus upstream time)
rather than end-to-end latency, because upstream time dominates the total and is
stochastic. Measured at low concurrency on purpose: once the event loop
saturates, "gateway overhead" is queueing delay and the span cost is
unmeasurable underneath it.

Honest caveat: on SQLite on a laptop this figure ranges from well under a
millisecond to roughly ten milliseconds between runs, because request
persistence contends with it. The stable claim is that the absolute cost is
small and the mechanism is measured, not that a specific percentage holds.

---

## 5. Data model

```
model_catalog ────────┐   price book + capability tier + simulated behaviour
  slug, provider,     │
  tier, prices,       │
  expected latency    │
                      ▼
routing_policies ──▶ inference_requests ──▶ spans
  strategy,            resolved model,        trace tree with events
  candidates,          routing reason,        (first_token, retries)
  weights, fallbacks,  tokens, cost,
  shadow               baseline, saved,
                       ttft / latency /
                       upstream / overhead
                            │
cache_entries          api_keys              provider_health
  canonical hash,        rpm/tpm limits,       circuit state,
  completion, hits,      monthly budget,       failure counts
  avoided spend          attributed spend

load_tests    alerts    audit_events    platform_config
```

Notable choices:

- **Prices are rows, not constants.** Every cost figure traces to a catalogue row
  an operator can edit, with `price_verified_at` and `price_source` so a stale
  price book is visible rather than silently wrong.
- **`baseline_cost_usd` on every request.** The counterfactual is stored at
  request time, so the savings figure survives later price edits and does not
  need recomputation.
- **A `DateTime` `TypeDecorator`** normalises to naive UTC on SQLite and aware UTC
  on Postgres, keeping application code free of naive/aware comparison bugs.
- **`platform_config`** holds the runtime policy the hot path reads, so toggling
  the cache or tracing takes effect on the next request.

---

## 6. Observability surface

| Metric | Type | Labels |
| --- | --- | --- |
| `sentinel_inferences_total` | counter | model, provider, cache, status |
| `sentinel_inference_duration_seconds` | histogram | model, provider |
| `sentinel_time_to_first_token_seconds` | histogram | model, provider |
| `sentinel_output_tokens_per_second` | histogram | model |
| `sentinel_tokens_total` | counter | model, provider, direction |
| `sentinel_cost_usd_total` | counter | model, provider |
| `sentinel_savings_usd_total` | counter | source (routing / cache) |
| `sentinel_upstream_retries_total` | counter | provider, reason |
| `sentinel_circuit_state` | gauge | provider |
| `sentinel_inflight_requests` | gauge | — |
| `sentinel_concurrency_wait_seconds` | histogram | — |
| `sentinel_cache_operations_total` | counter | outcome |
| `sentinel_rate_limited_total` | counter | reason |
| `sentinel_guard_blocks_total` | counter | rule, action |
| `sentinel_spans_recorded_total`, `sentinel_trace_flush_seconds` | counter, histogram | — |
| `sentinel_http_requests_total`, `..._duration_seconds` | counter, histogram | method, route, status |

Recording rules and alerts are in `infra/prometheus/rules.yml`; a provisioned
Grafana dashboard covers traffic, TTFT percentiles, spend rate, throughput,
circuit state, retries and the tracing cost.

---

## 7. Autoscaling

CPU is a poor scaling signal for an I/O-bound gateway: a pod waiting on an
upstream is busy but idle. `sentinel_inflight_requests` is the right signal, and
the KEDA `ScaledObject` in `infra/k8s/base/autoscaling.yaml` targets it with p95
TTFT as a secondary trigger.

The threshold is not guessed. Run the built-in load test, read the stage table,
and find the concurrency where throughput stops climbing while `overhead_p50`
starts rising — that is queueing, and the per-replica target belongs just below
it. On a development laptop against the local engine that point sits near 16
concurrent calls at roughly 25-35 requests/second; on real hardware with real
upstreams the number will differ, which is exactly why the harness ships with the
gateway instead of being a one-off script.

---

## 8. Security posture

- Operator access is a JWT signed with `JWT_SECRET`; credentials come from
  `ADMIN_EMAIL` / `ADMIN_PASSWORD`, compared with `hmac.compare_digest`.
- Service keys are `sk-sent-`-prefixed, stored as PBKDF2-SHA256 (120k rounds,
  per-key salt), indexed by prefix, and revealed in plaintext exactly once.
- `PUBLIC_READ` and `ALLOW_ANONYMOUS_INFERENCE` default to true for a public
  demo. Both should be false anywhere real; mutations always require the operator
  token regardless.
- Containers run as UID 10001, non-root, read-only root filesystem, all
  capabilities dropped, `RuntimeDefault` seccomp; the namespace enforces the
  `restricted` Pod Security Standard.
- Prompts and completions are stored truncated, after redaction. Nothing is
  logged to stdout.
- Upstream credentials never leave the process: the console talks to the gateway,
  never to a provider.

**Known limitations, stated plainly:** rate-limit buckets and the SSE bus are
per process, so a fleet needs Redis and a shared bus; the schema is created with
`create_all` rather than migrations; there is no per-tenant data isolation beyond
key attribution; and the response cache is exact-match, not semantic.

---

## 9. Why a local inference engine exists

`providers/simulated.py` is not a stub standing in for missing work. Three things
depend on having an upstream whose latency, throughput and failure rate are
known and free:

1. **The load test.** A concurrency ramp against a paid provider is expensive and
   its numbers are dominated by someone else's queue.
2. **CI.** The pipeline asserts on routing, caching, failover and tracing on every
   push, with no secrets and no bill.
3. **The public demo.** Anyone can drive the console without a key.

It streams tokens at the configured rate, honours the caller's token budget, and
can be told to fail a set fraction of calls — which is how the failover
demonstration works. Four priced tiers exist so routing decisions and the
premium-baseline comparison have something real to choose between.
