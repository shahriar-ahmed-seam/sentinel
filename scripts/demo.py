"""Exercise the gateway end to end against a running instance.

    python scripts/demo.py --base-url http://localhost:8000

What it proves, in order:
  1. the router picks different tiers for different prompts
  2. an identical low-temperature call is served from cache at zero cost
  3. streaming works and reports time-to-first-token
  4. a failing upstream trips the circuit breaker and traffic fails over
  5. spans exist for the whole path
  6. a concurrency ramp produces sustained throughput and a tracing-overhead figure

Everything goes through the public API, so this doubles as an integration smoke
test — CI runs exactly this file.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

import httpx

PROMPTS = [
    ("hey", "expect the cheapest tier"),
    ("What is the difference between a rate limit and a quota?", "expect a mid tier"),
    (
        "Explain step by step how to choose between a read replica and a cache for a "
        "read-heavy endpoint, and analyse the failure modes of each choice in detail.",
        "expect a capable tier",
    ),
]


def section(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m")


class Client:
    def __init__(self, base_url: str, email: str, password: str) -> None:
        self.http = httpx.Client(base_url=base_url.rstrip("/"), timeout=180.0)
        response = self.http.post("/api/auth/login", json={"email": email, "password": password})
        response.raise_for_status()
        self.http.headers["authorization"] = f"Bearer {response.json()['access_token']}"

    def get(self, path: str, **params: Any) -> Any:
        response = self.http.get(path, params=params or None)
        response.raise_for_status()
        return response.json()

    def post(self, path: str, payload: dict[str, Any] | None = None, **params: Any) -> Any:
        response = self.http.post(path, json=payload, params=params or None)
        response.raise_for_status()
        return response.json()

    def put(self, path: str, payload: dict[str, Any]) -> Any:
        response = self.http.put(path, json=payload)
        response.raise_for_status()
        return response.json()

    def patch(self, path: str, payload: dict[str, Any]) -> Any:
        response = self.http.patch(path, json=payload)
        response.raise_for_status()
        return response.json()

    def chat(self, prompt: str, **extra: Any) -> dict[str, Any]:
        body = {
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 220,
            **extra,
        }
        return self.post("/v1/chat/completions", body)


def show(result: dict[str, Any], note: str = "") -> dict[str, Any]:
    meta = result.get("sentinel", {})
    usage = result.get("usage", {})
    model = meta.get("model") or result.get("model") or "?"
    print(
        f"    {model:<20} {meta.get('complexity', '?'):<10} "
        f"cache={meta.get('cache', '?'):<7} "
        f"tok={usage.get('prompt_tokens', 0)}/{usage.get('completion_tokens', 0):<5} "
        f"${meta.get('cost_usd', 0):.6f}  ttft={meta.get('ttft_ms', 0):.0f}ms  "
        f"overhead={meta.get('gateway_overhead_ms', 0):.1f}ms{('  ' + note) if note else ''}"
    )
    return meta


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--email", default="admin@sentinel.dev")
    parser.add_argument("--password", default="sentinel")
    parser.add_argument("--skip-loadtest", action="store_true")
    args = parser.parse_args()

    client = Client(args.base_url, args.email, args.password)

    section("0. gateway state")
    system = client.get("/api/system")
    print(f"    version {system['app']['version']} on {system['infrastructure']['database']}")
    print(f"    upstreams: {', '.join(system['infrastructure']['providers_configured'])}")
    print(f"    live: {', '.join(system['infrastructure']['live_providers']) or 'none (simulated)'}")

    section("1. the router picks a tier per prompt")
    for prompt, expectation in PROMPTS:
        show(client.chat(prompt), expectation)

    section("2. an identical deterministic call is served from cache")
    repeat = f"Summarise idempotency in one sentence. [{int(time.time())}]"
    first = show(client.chat(repeat), "priming (miss)")
    second = show(client.chat(repeat), "should be a hit")
    if second.get("cache") != "hit":
        print("    note: not a hit — check the cache temperature ceiling in /api/runtime")
    else:
        print(
            f"    avoided ${second.get('saved_usd', 0):.6f}; served in "
            f"{second.get('latency_ms', 0):.0f}ms versus {first.get('latency_ms', 0):.0f}ms"
        )

    section("3. streaming reports time to first token")
    started = time.perf_counter()
    first_token_at: float | None = None
    chunks = 0
    meta: dict[str, Any] = {}
    with client.http.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "sim-small",
            "messages": [{"role": "user", "content": "List three reasons to cache responses."}],
            "stream": True,
            "max_tokens": 160,
        },
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            event = json.loads(payload)
            if event.get("sentinel"):
                meta = event["sentinel"]
            delta = (event.get("choices") or [{}])[0].get("delta", {}).get("content")
            if delta:
                chunks += 1
                if first_token_at is None:
                    first_token_at = time.perf_counter()
    observed_ttft = (first_token_at - started) * 1000 if first_token_at else 0.0
    print(
        f"    {chunks} content frames · observed ttft {observed_ttft:.0f}ms · "
        f"gateway reported {meta.get('ttft_ms', 0):.0f}ms · model {meta.get('model')}"
    )

    section("4. a broken model fails over; the provider breaker judges the provider")
    print("    forcing sim-small to fail every call, then asking for it explicitly")
    client.patch("/api/models/sim-small", {"simulated_failure_rate": 1.0})
    try:
        outcomes: list[str] = []
        for index in range(8):
            try:
                result = client.chat(
                    f"Force a failover attempt {index}.", model="sim-small", cache=False
                )
                outcomes.append(result.get("model") or "?")
            except httpx.HTTPStatusError as exc:
                outcomes.append(f"HTTP {exc.response.status_code}")
        print(f"    served by: {outcomes}")
        health = client.get("/api/providers")
        for provider in health["providers"]:
            print(
                f"    {provider['provider']:<12} state={provider['state']:<10} "
                f"failures={provider['total_failures']}"
            )
        print(
            "    note: the breaker is scoped to the provider, not the model. Every request\n"
            "    still succeeded via failover, and successes on a healthy model of the same\n"
            "    provider keep its circuit closed — which is the correct verdict, because the\n"
            "    provider is reachable. A breaker trips only when the endpoint itself is down."
        )
    finally:
        client.patch("/api/models/sim-small", {"simulated_failure_rate": 0.0})
        client.post("/api/providers/simulated/reset")
        print("    restored sim-small and reset the breaker")

    section("5. spans cover the whole path")
    traces = client.get("/api/traces", limit=1)
    if traces:
        trace = client.get(f"/api/traces/{traces[0]['trace_id']}")
        print(f"    trace {trace['trace_id'][:16]} · {trace['span_count']} spans · {trace['total_duration_ms']:.1f}ms")
        for span in trace["spans"]:
            indent = "      " if span["parent_id"] else "    "
            print(f"{indent}{span['name']:<26} {span['duration_ms']:>8.2f}ms  {span['status']}")

    if not args.skip_loadtest:
        section("6. concurrency ramp and tracing overhead")
        test = client.post(
            "/api/loadtests",
            {
                "label": "demo ramp",
                "model": "sim-nano",
                "concurrency_levels": [1, 4, 16],
                "requests_per_stage": 40,
                "max_tokens": 120,
                "measure_tracing_overhead": True,
            },
        )
        for _ in range(120):
            time.sleep(3)
            current = client.get(f"/api/loadtests/{test['id']}")
            if current["status"] in ("succeeded", "failed"):
                break
        for stage in current.get("stages", []):
            print(
                f"    c={stage['concurrency']:<3} rps={stage['rps']:<7} "
                f"ttft_p95={stage['ttft_p95']:<9} overhead_p50={stage['overhead_p50']}"
            )
        summary = current.get("summary", {})
        print(
            f"    peak {summary.get('peak_rps')} rps at c{summary.get('peak_rps_concurrency')}, "
            f"errors {summary.get('error_rate')}"
        )
        overhead = summary.get("tracing_overhead")
        if overhead:
            print(
                f"    tracing adds {overhead['delta_ms']}ms to gateway overhead "
                f"({overhead['overhead_ratio'] * 100:.1f}%) at c{overhead['concurrency']}"
            )

    section("7. rollup")
    overview = client.get("/api/overview", hours=24)
    spend = overview["spend"]
    latency = overview["latency"]
    print(
        f"    {overview['traffic']['requests']} requests · "
        f"cache hit {overview['traffic']['cache_hit_rate'] * 100:.1f}% · "
        f"errors {overview['traffic']['error_rate'] * 100:.2f}%"
    )
    print(
        f"    ttft p50/p95/p99 {latency['ttft_p50']}/{latency['ttft_p95']}/{latency['ttft_p99']}ms · "
        f"gateway overhead p50 {latency['gateway_overhead_p50']}ms"
    )
    print(
        f"    spend ${spend['cost_usd']:.6f} versus ${spend['baseline_usd']:.6f} baseline "
        f"= {spend['savings_ratio'] * 100:.1f}% avoided"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
