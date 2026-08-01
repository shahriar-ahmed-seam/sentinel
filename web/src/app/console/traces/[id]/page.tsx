"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { Empty, KeyValue, Panel, PanelHeader, SectionTitle, Skeleton, StatusPill } from "@/components/ui";
import { TraceWaterfall } from "@/components/waterfall";
import { int, ms, num, shortId, stamp } from "@/lib/format";
import { usePoll } from "@/lib/hooks";
import type { Trace } from "@/lib/types";

export default function TraceDetailPage() {
  const params = useParams<{ id: string }>();
  const traceId = params.id;
  const { data: trace, error } = usePoll<Trace>(`/api/traces/${traceId}`, 0);

  if (error) {
    return (
      <Empty
        title="Trace not found"
        hint="Spans are pruned on a retention window; the request row may still exist."
        action={
          <Link href="/console/traces" className="text-[12px] text-signal">
            back to traces →
          </Link>
        }
      />
    );
  }
  if (!trace) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-80" />
        <Skeleton className="h-72" />
      </div>
    );
  }

  const request = trace.request;
  const upstream = trace.spans.find((s) => s.name.startsWith("upstream."));
  const route = trace.spans.find((s) => s.name === "route.decide");
  const cacheSpan = trace.spans.find((s) => s.name === "cache.lookup");

  return (
    <div className="space-y-5">
      <div>
        <div className="flex items-center gap-2 text-[11px] text-faint">
          <Link href="/console/traces" className="transition-colors hover:text-muted">
            traces
          </Link>
          <span>/</span>
          <span className="num text-muted">{shortId(traceId, 20)}</span>
        </div>
        <SectionTitle
          hint={`${trace.span_count} spans spanning ${ms(trace.total_duration_ms)}. Bars are positioned on a shared time axis; yellow ticks are span events such as first-token.`}
        >
          Trace
        </SectionTitle>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Panel className="xl:col-span-2">
          <PanelHeader title="Waterfall" />
          <TraceWaterfall spans={trace.spans} />
        </Panel>

        <div className="space-y-4">
          {request ? (
            <Panel>
              <PanelHeader
                title="Request"
                action={
                  <StatusPill status={request.status === "ok" ? "succeeded" : request.status} />
                }
              />
              <KeyValue
                rows={[
                  ["When", stamp(request.created_at)],
                  ["Model", request.resolved_model],
                  ["Provider", request.provider],
                  ["Policy", request.policy],
                  ["Complexity", request.complexity],
                  ["Cache", request.cache_state],
                  ["Tokens", `${int(request.prompt_tokens)} / ${int(request.completion_tokens)}`],
                  ["Cost", `$${num(request.cost_usd, 8)}`],
                  ["TTFT", ms(request.ttft_ms)],
                  ["End to end", ms(request.latency_ms)],
                  ["Gateway overhead", ms(request.overhead_ms)],
                ]}
              />
              <div className="mt-3">
                <Link
                  href={`/console/requests?id=${request.id}`}
                  className="text-[11px] text-muted underline transition-colors hover:text-signal"
                >
                  open in the request log
                </Link>
              </div>
            </Panel>
          ) : null}

          <Panel>
            <PanelHeader title="Latency breakdown" hint="Where the wall-clock time went." />
            <KeyValue
              rows={[
                ["Total", ms(trace.total_duration_ms)],
                ["Routing decision", route ? ms(route.duration_ms) : "—"],
                ["Cache lookup", cacheSpan ? ms(cacheSpan.duration_ms) : "not attempted"],
                ["Upstream call", upstream ? ms(upstream.duration_ms) : "—"],
                [
                  "Everything else",
                  ms(
                    Math.max(
                      0,
                      trace.total_duration_ms -
                        (upstream?.duration_ms ?? 0) -
                        (route?.duration_ms ?? 0) -
                        (cacheSpan?.duration_ms ?? 0),
                    ),
                  ),
                ],
              ]}
            />
            {route?.attributes?.reason ? (
              <p className="mt-3 rounded-lg border border-line bg-raised/50 p-2.5 text-[11.5px] leading-relaxed text-muted">
                {String(route.attributes.reason)}
              </p>
            ) : null}
          </Panel>
        </div>
      </div>
    </div>
  );
}
