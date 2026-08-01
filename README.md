<div align="center">

# Sentinel

**A model-serving gateway with the observability an operator actually needs.**
Route every prompt to the cheapest capable model, account for every token,
trace every hop, and keep serving when an upstream breaks.

[![ci](https://github.com/shahriar-ahmed-seam/sentinel/actions/workflows/ci.yml/badge.svg)](https://github.com/shahriar-ahmed-seam/sentinel/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-MIT-22d3ee)](LICENSE)
[![python](https://img.shields.io/badge/python-3.10%20|%203.12-3776ab)](services/gateway/requirements.txt)
[![next](https://img.shields.io/badge/next.js-16-000)](web/package.json)

[Architecture](docs/architecture.md) · [Quickstart](#quickstart) · [What it measures](#what-it-measures)

**[Live console](https://sentinel-console-xi.vercel.app)**

<sub>The console ships pointed at a hosted gateway. Running the gateway yourself is two
commands — see [Quickstart](#quickstart) — and it needs no API key, because the built-in
deterministic engine serves traffic locally with real priced tiers.</sub>

</div>

---

## Why this exists

Calling a model provider is one HTTP request. Operating that call is the part
teams keep rebuilding badly:

- **Cost is invisible until the invoice.** Spend aggregates per month, per
  provider, with no line back to the request. Nobody can answer *"what would this
  have cost on the cheaper model?"*
- **Latency is a single number.** Without time-to-first-token separated from
  generation time and gateway overhead, a slow endpoint has no diagnosis.
- **Failure is all-or-nothing.** No retry budget, no breaker, no failover. One
  provider incident becomes your incident, and the retry storm makes it worse.

Sentinel is a drop-in `/v1/chat/completions` endpoint that handles all three and
then reports on itself.

---

## The pipeline

```
guard ──▶ limits ──▶ route ──▶ cache ──▶ attempt chain ──▶ account ──▶ observe
  │         │          │         │            │              │           │
size cap  rpm/tpm   classify  canonical    retry +        tokens +    spans +
redact    budget    + policy  hash, TTL    failover +     price book  metrics +
output    semaphore  choice   re-stream    breaker        + baseline  SSE feed
```

Every stage emits a span, so any request's waterfall shows where its
milliseconds went and which decision produced its cost.

---

## Quickstart

### 60 seconds, no keys, no infrastructure

```bash
cd services/gateway
pip install -r requirements.txt
uvicorn sentinel.main:app --port 8000
```

It starts on SQLite, seeds a catalogue of six models, five routing policies and a
data-plane key, then sends a little warm-up traffic so the dashboard is not empty.
With no provider credentials it routes to a **deterministic local engine** that
streams tokens at a configured rate — which is what makes the load test, CI and a
public demo possible. Open <http://localhost:8000/docs>.

Add a real upstream any time:

```bash
echo "DEEPSEEK_API_KEY=sk-..." >> .env    # or OPENAI_API_KEY, or COMPAT_BASE_URL
```

Then the console:

```bash
cd web
npm install
echo "NEXT_PUBLIC_API_URL=http://127.0.0.1:8000" > .env.local
npm run dev          # http://localhost:3000
```

Sign in with `admin@sentinel.dev` / `sentinel` (change both before exposing it).

### Full stack with Postgres, Prometheus, Grafana, Jaeger

```bash
docker compose up --build
```

| Service | URL |
| --- | --- |
| Console | <http://localhost:3000> |
| Gateway docs | <http://localhost:8000/docs> |
| Prometheus | <http://localhost:9090> |
| Grafana | <http://localhost:3001> (`admin` / `admin`) |
| Jaeger | <http://localhost:16686> |

Spans go to an OpenTelemetry collector and on to Jaeger, so export is exercised
for real rather than assumed.

---

## Use it like the API you already have

```bash
curl -N http://localhost:8000/v1/chat/completions \
  -H "content-type: application/json" \
  -H "authorization: Bearer $SENTINEL_API_KEY" \
  -d '{
    "messages": [{"role": "user", "content": "Why can a p99 spike hide behind a healthy p50?"}],
    "stream": true,
    "policy": "cost-optimised"
  }'
```

Any OpenAI SDK works unchanged. The extra request fields (`policy`, `cache`,
`capabilities`) and the response's `sentinel` block are additive:

```json
{
  "model": "deepseek-chat",
  "choices": [{ "index": 0, "message": { "role": "assistant", "content": "…" } }],
  "usage": { "prompt_tokens": 28, "completion_tokens": 220, "total_tokens": 248 },
  "sentinel": {
    "model": "deepseek-chat",
    "provider": "deepseek",
    "policy": "cost-optimised",
    "strategy": "cheapest",
    "routing_reason": "cheapest model at or above tier 3 (estimated $0.000066 for ~30+220 tokens)",
    "complexity": "complex",
    "cache": "bypass",
    "cost_usd": 6.552e-05,
    "baseline_cost_usd": 0.00908,
    "saved_usd": 0.00901448,
    "ttft_ms": 882.14,
    "latency_ms": 2956.33,
    "gateway_overhead_ms": 12.67,
    "tokens_per_second": 106.72,
    "trace_id": "db8d537bf1d719fe0e073a4111c352f9"
  }
}
```

That is a real response from a local run against DeepSeek: the router picked the
live upstream over the premium simulated tier because it was genuinely cheaper for
a tier-3 prompt, and the gateway added 12.7 ms to a 2.96 s call.

---

## What it measures

`python scripts/demo.py` drives routing, caching, failover, tracing and a
concurrency ramp through the public API. Real output from a local run (SQLite,
4-core laptop, DeepSeek configured):

```
1. the router picks a tier per prompt
   sim-nano        trivial  cache=miss  tok=1/30     $0.000003  ttft=158ms  overhead=157ms
   sim-nano        trivial  cache=miss  tok=14/30    $0.000004  ttft=162ms  overhead=37ms
   deepseek-chat   complex  cache=miss  tok=35/220   $0.000067  ttft=929ms  overhead=26ms

2. an identical deterministic call is served from cache
   sim-nano        trivial  cache=miss  $0.000004   234ms
   sim-nano        trivial  cache=hit   $0.000000    33ms      avoided $0.000004

3. streaming reports time to first token
   10 content frames · gateway reported 192ms ttft · model sim-small

4. a broken model fails over
   sim-small forced to fail every call →
   served by: sim-large × 8      requests failed: 0
   simulated  state=closed  failures=24     deepseek  state=closed  failures=0

5. spans cover the whole path
   route.decide         19.43ms  ok
   upstream.simulated    0.16ms  error     ← retry 1
   upstream.simulated    0.18ms  error     ← retry 2
   upstream.simulated    0.49ms  error     ← retry 3, then failover

6. concurrency ramp
   c=1    rps=3.04    ttft_p95=184ms   overhead_p50=21ms
   c=4    rps=13.27   ttft_p95=150ms   overhead_p50=27ms
   c=16   rps=23.96   ttft_p95=154ms   overhead_p50=136ms   ← queueing starts
   peak 23.96 rps, errors 0.00%

7. rollup
   943 requests · errors 0.00% · ttft p50/p95/p99 128/173/692ms
   gateway overhead p50 24ms
   spend $0.014204 versus $1.986260 baseline = 96.7% avoided
```

Read the three headline numbers carefully — they are stated the way they were
measured, not the way they market best:

**Spend avoided: 96.7%.** The baseline is a counterfactual: the same tokens
priced against the most expensive *enabled* catalogue model. On this run that is
a simulated frontier tier at \$10/\$40 per MTok, so the ratio reflects the gap
between tiers in the seeded price book as much as the router's cleverness. The
mechanism is what transfers — the number moves with your catalogue.

**Saturation at c16, ~24-36 rps.** Throughput stops climbing while
`overhead_p50` jumps from 27 ms to 136 ms. That is queueing, not slow inference,
and it is exactly where an autoscaling threshold belongs. Absolute rps here is a
laptop against a local engine; the *shape* is what matters.

**Tracing overhead: single-digit milliseconds.** Measured by running the same
stage with span recording on and off and comparing gateway overhead (total minus
upstream time), at low concurrency so queueing does not swamp it. Across runs on
SQLite this landed between 0.5 ms (3.9%) and 9.2 ms (35%) — the variance comes
from request persistence contending on the same file. The honest claim is that
the absolute cost is small and the mechanism is measured; a stable percentage
needs Postgres and more samples.

---

## What is actually built

| | |
| --- | --- |
| **OpenAI-compatible data plane** | `/v1/chat/completions` with SSE streaming, `/v1/models`, delayed-usage reporting, vendor `sentinel` block |
| **Prompt-aware routing** | Rule-based complexity classifier plus cheapest / fastest / weighted / failover / quality-tier strategies, capability filters and cost ceilings |
| **Dry-run explainer** | `POST /api/policies/explain` returns the model it *would* pick with the full candidate set, costs and reason — no upstream called, nothing billed |
| **Shadow traffic** | Sample a fraction of calls to a comparison model off the caller's path, stored and diffable against the served answer |
| **Cost accounting** | Editable price book with `price_verified_at`, prompt-cache-hit rates, per-request cost and the premium-baseline counterfactual |
| **Response cache** | Canonical-hash exact match, temperature-gated, TTL + LRU eviction, re-streamed so client mechanics are identical |
| **Resilience** | Per-provider circuit breakers, jittered retry budgets, ordered failover, upstream timeouts, concurrency admission control |
| **Metering** | Hashed keys with per-key RPM/TPM limits and monthly budgets, spend attributed at request time |
| **Guardrails** | Prompt size caps, output clamps, PII and credential redaction inbound and outbound |
| **Tracing** | W3C span ids, inbound `traceparent` honoured, local waterfall viewer, optional OTLP mirroring, measured flush cost |
| **Load testing** | In-process concurrency ramp with TTFT percentiles, queueing detection and a tracing-overhead arm |
| **Runtime policy** | Cache, tracing, retries, breaker thresholds, limits and SLOs editable from the console, effective next request |
| **Console** | Overview, request log with trace waterfall, trace explorer, routing explainer, price book editor, streaming playground, load tests, settings |

---

## API surface

**Control plane** — operator JWT; `GET` is public when `PUBLIC_READ=true`.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/auth/login` | Operator token |
| `GET/POST/PATCH/DELETE` | `/api/auth/keys` | Service keys, limits, budgets |
| `GET` | `/api/overview` | Traffic, latency, spend, SLO, model mix, providers |
| `GET` | `/api/analytics/savings` | Avoided spend split by routing versus cache |
| `GET` | `/api/analytics/keys` | Per-key usage and budget consumption |
| `GET/PATCH` | `/api/models`, `/api/models/{slug}` | Catalogue and price book |
| `GET` | `/api/models/routable` | What can serve right now, and why not |
| `GET/PUT/DELETE` | `/api/policies` | Routing policies |
| `POST` | `/api/policies/explain` | Dry-run the router |
| `POST` | `/api/policies/{name}/default` | Switch the active policy |
| `GET` | `/api/requests`, `/api/requests/{id}` | Request log with routing detail |
| `GET` | `/api/requests/{id}/shadow` | The comparison call, if any |
| `GET` | `/api/traces`, `/api/traces/{trace_id}` | Span trees |
| `GET/PUT` | `/api/runtime` | Live gateway policy |
| `GET/DELETE` | `/api/cache` | Cache stats and purge |
| `GET/POST` | `/api/providers`, `/api/providers/{p}/reset` | Circuit state and manual reset |
| `GET/POST` | `/api/loadtests` | Submit and read load tests |
| `GET` | `/api/alerts`, `/api/audit` | Alerting and audit trail |
| `GET` | `/api/stream` | Server-sent events |
| `GET` | `/health`, `/health/ready`, `/metrics` | Liveness, readiness, Prometheus |

---

## Configuration

Everything has a working default — see [`.env.example`](.env.example).

| Variable | Default | Notes |
| --- | --- | --- |
| `DATABASE_URL` | *(empty)* | Empty → SQLite. Accepts `postgres://` and `?sslmode=require` |
| `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` | *(empty)* | Each adds a provider to the routing pool |
| `COMPAT_BASE_URL` + `COMPAT_API_KEY` | *(empty)* | Ollama, vLLM, Groq, Together, OpenRouter |
| `SIMULATE_ONLY` | `false` | Force the local engine even with keys present |
| `JWT_SECRET` | `change-me-in-production` | **Change it** |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | `admin@sentinel.dev` / `sentinel` | **Change them** |
| `PUBLIC_READ` | `true` | Control-plane `GET` without a token |
| `ALLOW_ANONYMOUS_INFERENCE` | `true` | `/v1` without a key. Set `false` for anything real |
| `CACHE_MAX_TEMPERATURE` | `0.25` | Above this, caching needs an explicit opt-in |
| `MAX_CONCURRENCY` | `64` | Admission-control ceiling per process |
| `CIRCUIT_FAILURE_THRESHOLD` | `5` | Consecutive failures before opening |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | *(empty)* | Set to mirror spans; needs `requirements-optional.txt` |
| `SLO_TTFT_MS` | `1500` | What the dashboard grades against |
| `NEXT_PUBLIC_API_URL` | *(empty)* | Console → gateway. Empty = same origin |

---

## Layout

```
sentinel/
├─ services/gateway/
│  ├─ sentinel/
│  │  ├─ main.py            app assembly, lifespan, janitor
│  │  ├─ gateway.py         the request pipeline
│  │  ├─ policy.py          classifier-driven routing + strategies
│  │  ├─ pricing.py         token accounting, cost math, seed price book
│  │  ├─ cache.py           canonical-hash response cache
│  │  ├─ circuit.py         per-provider breakers
│  │  ├─ limits.py          token buckets, budgets, admission control
│  │  ├─ guard.py           size caps and redaction
│  │  ├─ tracing.py         W3C spans, buffered flush, optional OTLP
│  │  ├─ loadtest.py        concurrency ramp + tracing-overhead arm
│  │  ├─ runtime.py         live-editable policy
│  │  ├─ providers/         base · openai_compat · simulated · registry
│  │  └─ routers/           inference · catalog · traffic · analytics · ops · auth · system
│  └─ Dockerfile
├─ web/                     Next.js 16 console
│  └─ src/{app,components,lib}
├─ infra/
│  ├─ prometheus/           scrape config, recording rules, alerts
│  ├─ grafana/              provisioned datasources + dashboard
│  ├─ otel/                 collector config
│  └─ k8s/{base,overlays}   Kustomize, KEDA ScaledObject, PDB, ServiceMonitor
├─ scripts/demo.py          end-to-end exercise, also the CI smoke test
├─ .github/workflows/       ci (lint, smoke, images, manifest validation) + release
├─ docker-compose.yml  render.yaml  Makefile
└─ docs/architecture.md
```

---

## Deployment

| Piece | Where | URL |
| --- | --- | --- |
| Console | Vercel, root dir `web/` | https://sentinel-console-xi.vercel.app |
| Gateway | Render, Docker (`render.yaml`) | set `NEXT_PUBLIC_API_URL` to its origin |
| Database | Neon Postgres, `eu-central-1` | `DATABASE_URL` |

**Gateway → Render.** `render.yaml` is a ready blueprint: Docker build, health
check, generated `JWT_SECRET`. Point `DATABASE_URL` at Neon or Render Postgres so
request history and traces survive a redeploy.

**Console → Vercel.** Import `web/`, set `NEXT_PUBLIC_API_URL` to the gateway
origin. `vercel.json` ships the security headers.

**Kubernetes.** `kubectl apply -k infra/k8s/overlays/production` gives the gateway
Deployment (non-root, read-only rootfs, all capabilities dropped, preStop drain so
streams finish and spans flush), the console, an ingress that routes `/v1`,
`/api`, `/docs` and `/health` to the gateway with buffering disabled for SSE, a
`ServiceMonitor`, and a **KEDA `ScaledObject` that scales on
`sentinel_inflight_requests`** rather than CPU — because a pod waiting on an
upstream is busy but idle.

CI runs lint, type checks, the full end-to-end smoke test (asserting that traffic
was recorded, a baseline cost was computed, a trace contains both a routing and an
upstream span, and the expected metrics are exported), both image builds, and
`kubeconform` validation of the rendered manifests.

---

## Deliberate non-goals

- **Per-process state.** Rate-limit buckets, the SSE bus and the span buffer live
  in the process. A fleet needs Redis and a shared bus; the effective rate ceiling
  is otherwise N × the configured value.
- **`create_all`, not migrations.** Correct for greenfield; Alembic is the answer
  once the schema is in production.
- **Exact-match caching only.** Semantic caching needs an embedding hop and a
  similarity threshold, which is a different set of trade-offs.
- **Guardrails are hygiene, not safety.** Size caps and redaction. Not a content
  moderation system, and it does not claim to be.
- **Chat completions only.** No embeddings, images or audio routes yet; the
  provider interface would extend cleanly but they are not written.
- **Seeded prices may be stale.** Live-provider rates are seeded from published
  figures and stamped with a verification date. Confirm them before quoting the
  cost numbers.

---

## Credits

Built by **Shahriar Ahmed Seam** ·
[github.com/shahriar-ahmed-seam](https://github.com/shahriar-ahmed-seam) for
Somokolon Labs. Photography via [Pexels](https://www.pexels.com) (Suki Lee,
Brett Sayles). DeepSeek price seeds from the provider's
[published pricing](https://api-docs.deepseek.com/quick_start/pricing). MIT
licensed.
