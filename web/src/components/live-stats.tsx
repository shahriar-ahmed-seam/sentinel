"use client";

import { int, ms, num, pct } from "@/lib/format";
import { usePoll } from "@/lib/hooks";
import type { Overview } from "@/lib/types";

/** Landing-page proof: these come from the running gateway, not a screenshot. */
export function LiveStats() {
  const { data, error } = usePoll<Overview>("/api/overview?hours=168", 15000);

  const cells = [
    {
      label: "spend avoided",
      value: data ? pct(data.spend.savings_ratio, 1) : "—",
      hint: data
        ? `$${num(data.spend.saved_usd, 4)} of $${num(data.spend.baseline_usd, 4)} baseline`
        : "versus the premium model",
    },
    {
      label: "requests routed",
      value: data ? int(data.traffic.requests) : "—",
      hint: data ? `errors ${pct(data.traffic.error_rate, 2)}` : "last 7 days",
    },
    {
      label: "ttft p95",
      value: data ? ms(data.latency.ttft_p95) : "—",
      hint: data ? `p50 ${ms(data.latency.ttft_p50)}` : "time to first token",
    },
    {
      label: "gateway overhead",
      value: data ? ms(data.latency.gateway_overhead_p50) : "—",
      hint: data ? `p95 ${ms(data.latency.gateway_overhead_p95)}` : "excludes upstream time",
    },
    {
      label: "cache hit rate",
      value: data ? pct(data.traffic.cache_hit_rate, 1) : "—",
      hint: data ? `${int(data.cache.entries)} entries` : "exact-match cache",
    },
  ];

  return (
    <div>
      <div className="grid grid-cols-2 divide-line border-y border-line md:grid-cols-5 md:divide-x">
        {cells.map((cell) => (
          <div key={cell.label} className="px-4 py-5 md:px-5">
            <p className="label-xs">{cell.label}</p>
            <p className="num mt-2 text-[26px] font-semibold leading-none tracking-tight text-ink">
              {cell.value}
            </p>
            <p className="mt-1.5 text-[11px] text-faint">{cell.hint}</p>
          </div>
        ))}
      </div>
      <p className="mt-3 flex items-center gap-2 text-[11px] text-faint">
        <i
          className={`size-1.5 rounded-full ${error ? "bg-crit" : data ? "bg-ok pulse-dot" : "bg-faint"}`}
        />
        {error
          ? "gateway unreachable — these fill in once the API is running"
          : data
            ? `read live from the gateway · ${data.window_hours}h window · updated ${new Date(
                data.generated_at,
              ).toLocaleTimeString("en-GB", { hour12: false })}`
            : "connecting to the gateway"}
      </p>
    </div>
  );
}

export function LiveRoutingNote() {
  const { data } = usePoll<Overview>("/api/overview?hours=168", 30000);
  if (!data?.models.length) return null;
  const top = data.models[0];
  return (
    <p className="num text-[11px] text-faint">
      busiest route: <span className="text-signal">{top.model}</span> at {pct(top.share, 0)} of
      traffic, {ms(top.ttft_p95)} p95
    </p>
  );
}
