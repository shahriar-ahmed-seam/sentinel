"use client";

import Link from "next/link";
import { LatencyChart, Sparkline, ThroughputChart } from "@/components/charts";
import {
  Bar,
  Empty,
  Panel,
  PanelHeader,
  Pill,
  SectionTitle,
  Skeleton,
  Stat,
  StatusPill,
  Table,
  Td,
} from "@/components/ui";
import { ago, clock, int, ms, num, pct } from "@/lib/format";
import { useEventStream, usePoll } from "@/lib/hooks";
import type { Alert, InferenceRequestRow, Overview, Savings } from "@/lib/types";

export default function OverviewPage() {
  const { data, loading } = usePoll<Overview>("/api/overview?hours=24&bucket_minutes=15", 8000);
  const { data: savings } = usePoll<Savings>("/api/analytics/savings?hours=168", 30000);
  const { data: recent } = usePoll<InferenceRequestRow[]>("/api/requests?limit=12", 6000);
  const { data: alerts } = usePoll<Alert[]>("/api/alerts?limit=6", 20000);
  const { events } = useEventStream(60);

  if (loading && !data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-72" />
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
        <Skeleton className="h-64" />
      </div>
    );
  }
  if (!data) return <Empty title="Gateway unreachable" hint="Check the API URL and CORS." />;

  const series = data.series;
  const spark = series.slice(-24).map((p) => p.requests);
  const slo = data.slo;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <SectionTitle hint="Every model call that passed through the gateway: what it cost, where it went, how long it took and whether an upstream misbehaved.">
          Gateway overview
        </SectionTitle>
        <p className="num text-[11px] text-faint">
          refreshed {clock(data.generated_at)} · window {data.window_hours}h
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <Stat
          label="Spend avoided"
          tone="signal"
          value={pct(data.spend.savings_ratio, 1)}
          sub={`$${num(data.spend.saved_usd, 4)} of $${num(data.spend.baseline_usd, 4)} baseline`}
        />
        <Stat
          label="Requests"
          value={int(data.traffic.requests)}
          sub={`${num(data.traffic.requests_per_minute, 2)}/min · errors ${pct(data.traffic.error_rate, 2)}`}
          chart={spark.length > 2 ? <Sparkline values={spark} /> : undefined}
        />
        <Stat
          label="TTFT p95"
          tone={data.latency.ttft_p95 > slo.ttft_target_ms ? "warn" : "ok"}
          value={ms(data.latency.ttft_p95)}
          sub={`p50 ${ms(data.latency.ttft_p50)} · target ${ms(slo.ttft_target_ms)}`}
        />
        <Stat
          label="Gateway overhead"
          value={ms(data.latency.gateway_overhead_p50)}
          sub={`p95 ${ms(data.latency.gateway_overhead_p95)} · excludes upstream time`}
        />
        <Stat
          label="Cache hit rate"
          tone={data.traffic.cache_hit_rate > 0.2 ? "ok" : "neutral"}
          value={pct(data.traffic.cache_hit_rate, 1)}
          sub={`${int(data.cache.entries)} entries · $${num(data.cache.saved_usd, 4)} avoided`}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Panel className="xl:col-span-2">
          <PanelHeader
            title="Request volume"
            hint={`${int(data.traffic.requests)} calls in ${data.window_hours}h · ${int(data.traffic.cache_hits)} served from cache`}
          />
          {series.length > 1 ? (
            <ThroughputChart data={series} />
          ) : (
            <Empty
              title="No traffic yet"
              hint="Send a request from the playground or run a load test."
            />
          )}
        </Panel>

        <Panel>
          <PanelHeader title="Service objectives" hint="Measured against the runtime policy." />
          <div className="space-y-4">
            <Objective
              label="TTFT attainment"
              value={slo.ttft_attainment}
              caption={`${pct(slo.ttft_attainment, 2)} of calls under ${ms(slo.ttft_target_ms)}`}
              tone={slo.ttft_attainment >= 0.95 ? "ok" : "warn"}
            />
            <Objective
              label="Availability"
              value={slo.availability}
              caption={`target ${pct(slo.availability_target, 2)}`}
              tone={slo.availability >= slo.availability_target ? "ok" : "crit"}
            />
            <Objective
              label="Error budget remaining"
              value={Math.max(0, Math.min(1, slo.error_budget_remaining))}
              caption={
                slo.error_budget_remaining >= 1
                  ? "no budget consumed in this window"
                  : `${pct(1 - slo.error_budget_remaining, 1)} of the budget burned`
              }
              tone={slo.error_budget_remaining > 0.5 ? "ok" : "warn"}
            />
            <div className="grid grid-cols-2 gap-2 pt-1">
              <Mini label="in flight" value={`${data.concurrency.inflight}/${data.concurrency.max_concurrency}`} />
              <Mini label="peak in flight" value={String(data.concurrency.peak_inflight)} />
              <Mini label="tokens in" value={int(data.spend.tokens_in)} />
              <Mini label="tokens out" value={int(data.spend.tokens_out)} />
            </div>
          </div>
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Panel className="xl:col-span-2">
          <PanelHeader title="Latency percentiles" hint="Time to first token per bucket." />
          {series.length > 1 ? (
            <LatencyChart
              data={series.map((p) => ({
                t: p.t,
                p50_ms: p.ttft_p50,
                p95_ms: p.ttft_p95,
                p99_ms: p.latency_p95,
              }))}
            />
          ) : (
            <Empty title="No latency samples" />
          )}
          <p className="mt-2 text-[11px] text-faint">
            p50/p95 are time-to-first-token; the third series is end-to-end p95 for scale.
          </p>
        </Panel>

        <Panel>
          <PanelHeader
            title="Upstream health"
            hint="Circuit state per provider, tripped independently per replica."
          />
          {data.providers.length ? (
            <div className="space-y-2.5">
              {data.providers.map((provider) => (
                <div key={provider.provider} className="rounded-xl border border-line bg-raised/50 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="num text-[13px] text-ink">{provider.provider}</span>
                    <StatusPill status={provider.state === "closed" ? "live" : provider.state} />
                  </div>
                  <div className="mt-2 grid grid-cols-3 gap-2">
                    <Mini label="calls" value={int(provider.total_requests)} />
                    <Mini label="failures" value={int(provider.total_failures)} />
                    <Mini label="fail rate" value={pct(provider.failure_ratio, 1)} />
                  </div>
                  {provider.last_error ? (
                    <p className="mt-2 truncate text-[10.5px] text-crit/80">{provider.last_error}</p>
                  ) : null}
                </div>
              ))}
            </div>
          ) : (
            <Empty title="No upstream calls yet" />
          )}
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Panel className="xl:col-span-2">
          <PanelHeader
            title="Model mix"
            hint="Where traffic landed, and what each tier cost."
            action={
              <Link
                href="/console/models"
                className="text-[11px] text-muted transition-colors hover:text-signal"
              >
                catalogue →
              </Link>
            }
          />
          {data.models.length ? (
            <Table head={["Model", "Provider", "Share", "Requests", "Cost", "TTFT p95", "tok/s"]}>
              {data.models.map((model) => (
                <tr key={model.model}>
                  <Td mono>{model.model}</Td>
                  <Td className="text-muted">{model.provider}</Td>
                  <Td>
                    <div className="flex items-center gap-2">
                      <Bar value={model.share} tone="signal" className="w-16" />
                      <span className="num text-[11px] text-faint">{pct(model.share, 0)}</span>
                    </div>
                  </Td>
                  <Td mono>{int(model.requests)}</Td>
                  <Td mono>${num(model.cost_usd, 5)}</Td>
                  <Td mono>{ms(model.ttft_p95)}</Td>
                  <Td mono>{num(model.tokens_per_second, 1)}</Td>
                </tr>
              ))}
            </Table>
          ) : (
            <Empty title="No model traffic" />
          )}
        </Panel>

        <Panel>
          <PanelHeader title="Prompt complexity mix" hint="What the router classified traffic as." />
          {Object.keys(data.mix.complexity).length ? (
            <div className="space-y-2.5">
              {Object.entries(data.mix.complexity)
                .sort((a, b) => b[1] - a[1])
                .map(([label, count]) => (
                  <div key={label}>
                    <div className="flex items-baseline justify-between text-[12px]">
                      <span className="text-muted capitalize">{label}</span>
                      <span className="num text-ink">{int(count)}</span>
                    </div>
                    <Bar
                      value={count / Math.max(data.traffic.requests, 1)}
                      tone={
                        label === "frontier"
                          ? "crit"
                          : label === "complex"
                            ? "warn"
                            : label === "standard"
                              ? "info"
                              : "ok"
                      }
                    />
                  </div>
                ))}
              <div className="border-t border-line pt-3">
                <p className="label-xs mb-2">policy mix</p>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(data.mix.policy).map(([name, count]) => (
                    <Pill key={name} tone="neutral">
                      {name} · {count}
                    </Pill>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <Empty title="Nothing classified yet" />
          )}
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Panel className="xl:col-span-2" padded={false}>
          <div className="flex items-center justify-between border-b border-line px-5 py-3">
            <h2 className="text-[13px] font-semibold tracking-tight">Recent requests</h2>
            <Link
              href="/console/requests"
              className="text-[11px] text-muted transition-colors hover:text-signal"
            >
              all requests →
            </Link>
          </div>
          <div className="px-5 py-3">
            {recent?.length ? (
              <Table head={["When", "Model", "Complexity", "Cache", "Tokens", "Cost", "TTFT"]}>
                {recent.map((row) => (
                  <tr key={row.id}>
                    <Td className="text-faint">
                      <Link
                        href={`/console/requests?id=${row.id}`}
                        className="transition-colors hover:text-signal"
                      >
                        {ago(row.created_at)}
                      </Link>
                    </Td>
                    <Td mono>{row.resolved_model || "—"}</Td>
                    <Td className="text-muted capitalize">{row.complexity || "—"}</Td>
                    <Td>
                      <Pill tone={row.cache_state === "hit" ? "ok" : "neutral"}>
                        {row.cache_state}
                      </Pill>
                    </Td>
                    <Td mono>{int(row.total_tokens)}</Td>
                    <Td mono>${num(row.cost_usd, 6)}</Td>
                    <Td mono>{row.status === "ok" ? ms(row.ttft_ms) : row.status}</Td>
                  </tr>
                ))}
              </Table>
            ) : (
              <Empty title="No requests logged" />
            )}
          </div>
        </Panel>

        <Panel>
          <PanelHeader title="Live feed" hint="Server-sent events from the gateway." />
          {events.length ? (
            <ul className="max-h-[300px] space-y-1.5 overflow-y-auto pr-1">
              {events.slice(0, 26).map((event, index) => (
                <li key={`${event.at}-${index}`} className="flex items-start gap-2 text-[11.5px]">
                  <span className="num shrink-0 text-[10px] text-faint">{clock(event.at)}</span>
                  <span
                    className={
                      event.kind.includes("fail") || event.kind === "alert"
                        ? "text-crit"
                        : event.kind === "cache.hit"
                          ? "text-ok"
                          : event.kind.startsWith("circuit")
                            ? "text-warn"
                            : "text-muted"
                    }
                  >
                    {describe(event)}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <Empty title="Waiting for events" />
          )}
        </Panel>
      </div>

      {savings ? (
        <Panel>
          <PanelHeader
            title="Where the savings came from"
            hint={savings.method}
            action={
              <Pill tone="signal">
                baseline: {savings.baseline_model ?? "—"}
              </Pill>
            }
          />
          <div className="grid gap-4 lg:grid-cols-4">
            <Mini label="baseline cost" value={`$${num(savings.baseline_usd, 4)}`} />
            <Mini label="actual cost" value={`$${num(savings.actual_usd, 4)}`} />
            <Mini label="avoided by routing" value={`$${num(savings.by_source.routing, 4)}`} />
            <Mini label="avoided by cache" value={`$${num(savings.by_source.cache, 4)}`} />
          </div>
          <div className="mt-4">
            <Table head={["Model", "Cache", "Requests", "Actual", "Baseline", "Avoided"]}>
              {savings.by_model.slice(0, 8).map((row, index) => (
                <tr key={`${row.model}-${row.cache_state}-${index}`}>
                  <Td mono>{row.model || "—"}</Td>
                  <Td className="text-muted">{row.cache_state}</Td>
                  <Td mono>{int(row.requests)}</Td>
                  <Td mono>${num(row.cost_usd, 6)}</Td>
                  <Td mono className="text-faint">
                    ${num(row.baseline_usd, 6)}
                  </Td>
                  <Td mono className="text-signal">
                    ${num(row.saved_usd, 6)}
                  </Td>
                </tr>
              ))}
            </Table>
          </div>
        </Panel>
      ) : null}

      {alerts?.length ? (
        <Panel>
          <PanelHeader title="Alerts" />
          <ul className="divide-y divide-line">
            {alerts.map((alert) => (
              <li key={alert.id} className="flex items-start gap-3 py-2.5">
                <Pill
                  tone={
                    alert.level === "critical" ? "crit" : alert.level === "warning" ? "warn" : "info"
                  }
                  dot
                >
                  {alert.level}
                </Pill>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[12.5px] text-ink">{alert.title}</p>
                  <p className="line-clamp-2 text-[11px] text-faint">{alert.message}</p>
                </div>
                <span className="num shrink-0 text-[10.5px] text-faint">
                  {ago(alert.created_at)}
                </span>
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
    </div>
  );
}

function Objective({
  label,
  value,
  caption,
  tone,
}: {
  label: string;
  value: number;
  caption: string;
  tone: "ok" | "warn" | "crit";
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between text-[12px]">
        <span className="text-muted">{label}</span>
        <span className="num text-ink">{pct(value, 2)}</span>
      </div>
      <Bar value={value} tone={tone} className="mt-1.5" />
      <p className="mt-1 text-[10.5px] text-faint">{caption}</p>
    </div>
  );
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line bg-raised/50 px-2 py-1.5">
      <p className="label-xs">{label}</p>
      <p className="num mt-0.5 text-[13px] text-ink">{value}</p>
    </div>
  );
}

function describe(event: { kind: string; data: Record<string, unknown> }): string {
  const d = event.data ?? {};
  switch (event.kind) {
    case "request.completed":
      return `${d.model} · ${d.tokens} tok · $${Number(d.cost_usd ?? 0).toFixed(6)} · ${d.ttft_ms}ms ttft`;
    case "request.failed":
      return `failed (${d.status}): ${String(d.error ?? "").slice(0, 60)}`;
    case "cache.hit":
      return `cache hit on ${d.model} · saved $${Number(d.saved_usd ?? 0).toFixed(6)}`;
    case "route.decision":
      return `routed to ${d.model} (${d.complexity}) via ${d.policy}`;
    case "circuit.changed":
      return `circuit ${d.provider}: ${d.from} → ${d.to}`;
    case "loadtest.stage":
      return `load stage c${d.concurrency} · ${d.rps} rps`;
    case "loadtest.finished":
      return `load test ${d.status} · peak ${d.peak_rps ?? "—"} rps`;
    case "alert":
      return String(d.title ?? "alert");
    case "audit":
      return `${d.actor} · ${d.action}`;
    case "catalog.changed":
      return `catalogue updated: ${d.slug}`;
    case "policy.changed":
      return `policy updated: ${d.name}`;
    case "hello":
      return "stream connected";
    default:
      return event.kind;
  }
}
