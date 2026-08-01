"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import {
  Empty,
  KeyValue,
  Panel,
  PanelHeader,
  Pill,
  SectionTitle,
  Select,
  Skeleton,
  StatusPill,
  Table,
  Td,
} from "@/components/ui";
import { TraceWaterfall } from "@/components/waterfall";
import { ago, int, ms, num, shortId, stamp } from "@/lib/format";
import { usePoll } from "@/lib/hooks";
import type { InferenceRequestRow, Overview, Trace } from "@/lib/types";

export default function RequestsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-64" />}>
      <RequestsView />
    </Suspense>
  );
}

function RequestsView() {
  const search = useSearchParams();
  const [model, setModel] = useState("");
  const [cache, setCache] = useState("");
  const [status, setStatus] = useState("");
  const [includeShadow, setIncludeShadow] = useState(false);
  const [picked, setPicked] = useState<string | null>(search.get("id"));

  const query = new URLSearchParams({ limit: "80" });
  if (model) query.set("model", model);
  if (cache) query.set("cache", cache);
  if (status) query.set("status", status);
  if (includeShadow) query.set("include_shadow", "true");

  const { data: rows } = usePoll<InferenceRequestRow[]>(`/api/requests?${query}`, 6000);
  const { data: overview } = usePoll<Overview>("/api/overview?hours=168", 60000);
  const activeId = picked ?? rows?.[0]?.id ?? null;
  const { data: detail } = usePoll<InferenceRequestRow>(
    activeId ? `/api/requests/${activeId}` : null,
    0,
  );
  const { data: trace } = usePoll<Trace>(
    detail?.trace_id ? `/api/traces/${detail.trace_id}` : null,
    0,
  );
  const { data: shadow } = usePoll<InferenceRequestRow[]>(
    activeId ? `/api/requests/${activeId}/shadow` : null,
    0,
  );

  const modelOptions = [
    { value: "", label: "all models" },
    ...(overview?.models ?? []).map((m) => ({ value: m.model, label: m.model })),
  ];

  const attempts = (detail?.meta?.attempts as
    | { model: string; provider: string; ok: boolean; ms: number; error?: string }[]
    | undefined) ?? [];
  const considered = (detail?.meta?.considered as
    | { slug: string; estimated_cost_usd: number; estimated_latency_ms: number; meets_tier: boolean }[]
    | undefined) ?? [];

  return (
    <div className="space-y-5">
      <SectionTitle hint="Every call, with the routing decision that produced it, the tokens it burned, what it cost against the premium baseline, and the trace that explains the latency.">
        Request log
      </SectionTitle>

      <Panel padded={false}>
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-5 py-3">
          <h2 className="mr-auto text-[13px] font-semibold tracking-tight">
            {rows ? `${rows.length} most recent` : "loading"}
          </h2>
          <Select value={model} onChange={setModel} options={modelOptions} className="w-44" />
          <Select
            value={cache}
            onChange={setCache}
            options={[
              { value: "", label: "any cache state" },
              { value: "hit", label: "cache hit" },
              { value: "miss", label: "cache miss" },
              { value: "bypass", label: "cache bypass" },
            ]}
            className="w-40"
          />
          <Select
            value={status}
            onChange={setStatus}
            options={[
              { value: "", label: "any status" },
              { value: "ok", label: "ok" },
              { value: "failed", label: "failed" },
              { value: "limited", label: "rate limited" },
              { value: "guard", label: "guard rejected" },
            ]}
            className="w-36"
          />
          <button
            type="button"
            onClick={() => setIncludeShadow((v) => !v)}
            className={`rounded-md px-2 py-1.5 text-[11px] transition-colors ${
              includeShadow ? "bg-signal/12 text-signal" : "text-faint hover:text-muted"
            }`}
          >
            shadow calls
          </button>
        </div>
        <div className="px-5 py-3">
          {!rows ? (
            <div className="space-y-2">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-9" />
              ))}
            </div>
          ) : rows.length ? (
            <Table
              head={["When", "Model", "Policy", "Complexity", "Cache", "Tokens", "Cost", "TTFT", "Status"]}
            >
              {rows.map((row) => (
                <tr
                  key={row.id}
                  onClick={() => setPicked(row.id)}
                  className={`cursor-pointer transition-colors ${
                    row.id === activeId ? "bg-signal/6" : "hover:bg-raised/40"
                  }`}
                >
                  <Td className="text-faint">{ago(row.created_at)}</Td>
                  <Td mono>
                    {row.resolved_model || "—"}
                    {row.shadow_of ? <span className="ml-1 text-[10px] text-violet">shadow</span> : null}
                  </Td>
                  <Td className="text-muted">{row.policy || "—"}</Td>
                  <Td className="text-muted capitalize">{row.complexity || "—"}</Td>
                  <Td>
                    <Pill tone={row.cache_state === "hit" ? "ok" : "neutral"}>{row.cache_state}</Pill>
                  </Td>
                  <Td mono>
                    {int(row.prompt_tokens)}/{int(row.completion_tokens)}
                  </Td>
                  <Td mono>${num(row.cost_usd, 6)}</Td>
                  <Td mono>{row.ttft_ms ? ms(row.ttft_ms) : "—"}</Td>
                  <Td>
                    <StatusPill status={row.status === "ok" ? "succeeded" : row.status} />
                  </Td>
                </tr>
              ))}
            </Table>
          ) : (
            <Empty title="No requests match these filters" />
          )}
        </div>
      </Panel>

      {detail ? (
        <>
          <div className="grid gap-4 xl:grid-cols-3">
            <Panel>
              <PanelHeader
                title={`Request ${shortId(detail.id, 10)}`}
                hint={detail.routing_reason}
                action={<StatusPill status={detail.status === "ok" ? "succeeded" : detail.status} />}
              />
              <KeyValue
                rows={[
                  ["When", stamp(detail.created_at)],
                  ["Client", detail.client],
                  ["Requested", detail.requested_model || "(router chose)"],
                  ["Resolved", detail.resolved_model],
                  ["Provider", detail.provider],
                  ["Policy", detail.policy],
                  ["Complexity", `${detail.complexity} (tier ${detail.required_tier})`],
                  ["Cache", detail.cache_state],
                  ["Streamed", detail.stream ? "yes" : "no"],
                  ["Attempts", String(detail.attempts)],
                  ["Temperature", num(detail.temperature, 2)],
                  [
                    "Trace",
                    detail.trace_id ? (
                      <Link
                        href={`/console/traces/${detail.trace_id}`}
                        className="transition-colors hover:text-signal"
                      >
                        {shortId(detail.trace_id, 12)}
                      </Link>
                    ) : (
                      "—"
                    ),
                  ],
                ]}
              />
            </Panel>

            <Panel>
              <PanelHeader title="Cost & tokens" hint="Against the premium-baseline counterfactual." />
              <KeyValue
                rows={[
                  ["Prompt tokens", int(detail.prompt_tokens)],
                  ["Completion tokens", int(detail.completion_tokens)],
                  ["Total tokens", int(detail.total_tokens)],
                  ["Cost", `$${num(detail.cost_usd, 8)}`],
                  ["Baseline cost", `$${num(detail.baseline_cost_usd, 8)}`],
                  ["Avoided", `$${num(detail.saved_usd, 8)}`],
                  ["TTFT", ms(detail.ttft_ms)],
                  ["End to end", ms(detail.latency_ms)],
                  ["Upstream", ms(detail.upstream_ms)],
                  ["Gateway overhead", ms(detail.overhead_ms)],
                  ["Throughput", `${num(detail.tokens_per_second, 1)} tok/s`],
                ]}
              />
              {detail.guard_flags.length ? (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {detail.guard_flags.map((flag) => (
                    <Pill key={flag} tone="warn">
                      {flag}
                    </Pill>
                  ))}
                </div>
              ) : null}
            </Panel>

            <Panel>
              <PanelHeader title="Attempt chain" hint="Retries and failovers, in order." />
              {attempts.length ? (
                <ol className="space-y-2">
                  {attempts.map((attempt, index) => (
                    <li
                      key={index}
                      className="rounded-lg border border-line bg-raised/50 px-2.5 py-2 text-[11.5px]"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="num text-ink">
                          {index + 1}. {attempt.model}
                        </span>
                        <Pill tone={attempt.ok ? "ok" : "crit"}>{attempt.ok ? "ok" : "failed"}</Pill>
                      </div>
                      <p className="num mt-0.5 text-[10.5px] text-faint">
                        {attempt.provider} · {ms(attempt.ms)}
                      </p>
                      {attempt.error ? (
                        <p className="mt-1 text-[10.5px] leading-relaxed text-crit/80">
                          {attempt.error}
                        </p>
                      ) : null}
                    </li>
                  ))}
                </ol>
              ) : (
                <Empty title="No attempt detail" />
              )}
              {considered.length ? (
                <div className="mt-3 border-t border-line pt-3">
                  <p className="label-xs mb-2">candidates considered</p>
                  <ul className="space-y-1">
                    {considered.map((candidate) => (
                      <li
                        key={candidate.slug}
                        className="flex items-baseline justify-between text-[11px]"
                      >
                        <span
                          className={`num ${candidate.slug === detail.resolved_model ? "text-signal" : "text-muted"}`}
                        >
                          {candidate.slug}
                        </span>
                        <span className="num text-faint">
                          ${num(candidate.estimated_cost_usd, 6)} ·{" "}
                          {ms(candidate.estimated_latency_ms)}
                          {candidate.meets_tier ? "" : " · under tier"}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </Panel>
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <Panel>
              <PanelHeader title="Prompt & completion" hint="Truncated previews, PII already redacted." />
              <div className="space-y-3">
                <div>
                  <p className="label-xs mb-1.5">prompt</p>
                  <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded-lg border border-line bg-base p-3 text-[11.5px] leading-relaxed text-muted">
                    {detail.prompt_preview || "(empty)"}
                  </pre>
                </div>
                <div>
                  <p className="label-xs mb-1.5">completion</p>
                  <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded-lg border border-line bg-base p-3 text-[11.5px] leading-relaxed text-muted">
                    {detail.completion_preview || detail.error || "(empty)"}
                  </pre>
                </div>
              </div>
            </Panel>

            <Panel>
              <PanelHeader
                title="Trace"
                hint={
                  trace
                    ? `${trace.span_count} spans over ${ms(trace.total_duration_ms)}`
                    : "spans may have been pruned by retention"
                }
                action={
                  detail.trace_id ? (
                    <Link
                      href={`/console/traces/${detail.trace_id}`}
                      className="text-[11px] text-muted transition-colors hover:text-signal"
                    >
                      full view →
                    </Link>
                  ) : undefined
                }
              />
              {trace?.spans.length ? (
                <TraceWaterfall spans={trace.spans} />
              ) : (
                <Empty title="No spans for this request" />
              )}
            </Panel>
          </div>

          {shadow?.length ? (
            <Panel>
              <PanelHeader
                title="Shadow comparison"
                hint="The same prompt sent to a comparison model off the caller's path."
              />
              <Table head={["Model", "Tokens", "Cost", "TTFT", "Latency", "Preview"]}>
                {shadow.map((row) => (
                  <tr key={row.id}>
                    <Td mono>{row.resolved_model}</Td>
                    <Td mono>{int(row.total_tokens)}</Td>
                    <Td mono>${num(row.cost_usd, 6)}</Td>
                    <Td mono>{ms(row.ttft_ms)}</Td>
                    <Td mono>{ms(row.latency_ms)}</Td>
                    <Td className="max-w-[320px] truncate text-right text-faint">
                      {row.completion_preview}
                    </Td>
                  </tr>
                ))}
              </Table>
            </Panel>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
