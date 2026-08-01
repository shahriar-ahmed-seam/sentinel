"use client";

import Link from "next/link";
import { Empty, Panel, Pill, SectionTitle, Skeleton, Table, Td } from "@/components/ui";
import { ago, ms, num, shortId } from "@/lib/format";
import { usePoll } from "@/lib/hooks";
import type { SystemInfo, TraceSummary } from "@/lib/types";

export default function TracesPage() {
  const { data: traces } = usePoll<TraceSummary[]>("/api/traces?limit=60", 8000);
  const { data: system } = usePoll<SystemInfo>("/api/system", 30000);

  return (
    <div className="space-y-5">
      <SectionTitle hint="Spans use W3C trace ids and honour an inbound traceparent header, so a caller's trace flows through the gateway into the upstream span. They are stored locally for this viewer and mirrored to an OTLP collector when one is configured.">
        Traces
      </SectionTitle>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Info label="tracing" value={system?.tracing.enabled ? "enabled" : "disabled"} />
        <Info label="buffered spans" value={String(system?.tracing.buffered_spans ?? "—")} />
        <Info label="dropped spans" value={String(system?.tracing.dropped_spans ?? "—")} />
        <Info
          label="otlp mirroring"
          value={
            system?.tracing.otlp_mirroring
              ? (system.infrastructure.otlp_endpoint ?? "on")
              : "local only"
          }
        />
      </div>

      <Panel padded={false}>
        <div className="border-b border-line px-5 py-3">
          <h2 className="text-[13px] font-semibold tracking-tight">Recent traces</h2>
        </div>
        <div className="px-5 py-3">
          {!traces ? (
            <div className="space-y-2">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-9" />
              ))}
            </div>
          ) : traces.length ? (
            <Table head={["When", "Trace", "Model", "Provider", "Cache", "TTFT", "Latency", "Cost"]}>
              {traces.map((trace) => (
                <tr key={trace.trace_id} className="hover:bg-raised/40">
                  <Td className="text-faint">{ago(trace.created_at)}</Td>
                  <Td mono>
                    <Link
                      href={`/console/traces/${trace.trace_id}`}
                      className="transition-colors hover:text-signal"
                    >
                      {shortId(trace.trace_id, 16)}
                    </Link>
                  </Td>
                  <Td mono>{trace.model || "—"}</Td>
                  <Td className="text-muted">{trace.provider || "—"}</Td>
                  <Td>
                    <Pill tone={trace.cache === "hit" ? "ok" : "neutral"}>{trace.cache}</Pill>
                  </Td>
                  <Td mono>{trace.ttft_ms ? ms(trace.ttft_ms) : "—"}</Td>
                  <Td mono>{ms(trace.latency_ms)}</Td>
                  <Td mono>${num(trace.cost_usd, 6)}</Td>
                </tr>
              ))}
            </Table>
          ) : (
            <Empty title="No traces recorded" hint="Send a request to generate one." />
          )}
        </div>
      </Panel>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel p-4">
      <p className="label-xs">{label}</p>
      <p className="num mt-2 truncate text-[15px] text-ink">{value}</p>
    </div>
  );
}
