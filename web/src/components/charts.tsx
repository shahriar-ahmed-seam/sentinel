"use client";

import type { ReactNode } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const COLORS = {
  signal: "#22d3ee",
  ok: "#34d399",
  warn: "#fbbf24",
  crit: "#fb7185",
  info: "#60a5fa",
  violet: "#a78bfa",
  faint: "#596173",
};

function TooltipBox({
  active,
  payload,
  label,
  formatter,
}: {
  active?: boolean;
  payload?: { name?: string; value?: number | string; color?: string }[];
  label?: string | number;
  formatter?: (value: number | string, name: string) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-line-strong bg-overlay/95 px-2.5 py-2 shadow-xl backdrop-blur">
      {label !== undefined ? (
        <p className="num mb-1 text-[10px] uppercase tracking-widest text-faint">{label}</p>
      ) : null}
      <ul className="space-y-0.5">
        {payload.map((entry, index) => (
          <li key={index} className="flex items-center gap-2 text-[11px]">
            <i className="size-1.5 rounded-full" style={{ background: entry.color }} />
            <span className="text-muted">{entry.name}</span>
            <span className="num ml-auto text-ink">
              {formatter && entry.value !== undefined
                ? formatter(entry.value, entry.name ?? "")
                : entry.value}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ChartFrame({ height = 220, children }: { height?: number; children: ReactNode }) {
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        {children as never}
      </ResponsiveContainer>
    </div>
  );
}

/* ------------------------------------------------------------- throughput */
export function ThroughputChart({
  data,
  height = 200,
}: {
  data: { t: string; requests: number; errors: number }[];
  height?: number;
}) {
  const shaped = data.map((point) => ({
    ...point,
    label: new Date(point.t).toLocaleTimeString("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }),
  }));
  return (
    <ChartFrame height={height}>
      <AreaChart data={shaped} margin={{ top: 6, right: 6, left: -22, bottom: 0 }}>
        <defs>
          <linearGradient id="req" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={COLORS.signal} stopOpacity={0.5} />
            <stop offset="100%" stopColor={COLORS.signal} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="label" tickLine={false} axisLine={false} minTickGap={26} />
        <YAxis tickLine={false} axisLine={false} width={44} />
        <Tooltip content={<TooltipBox />} />
        <Area
          type="monotone"
          dataKey="requests"
          name="requests"
          stroke={COLORS.signal}
          strokeWidth={1.6}
          fill="url(#req)"
        />
      </AreaChart>
    </ChartFrame>
  );
}

export function LatencyChart({
  data,
  height = 200,
}: {
  data: { t: string; p50_ms: number; p95_ms: number; p99_ms: number }[];
  height?: number;
}) {
  const shaped = data.map((point) => ({
    ...point,
    label: new Date(point.t).toLocaleTimeString("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }),
  }));
  return (
    <ChartFrame height={height}>
      <LineChart data={shaped} margin={{ top: 6, right: 6, left: -22, bottom: 0 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="label" tickLine={false} axisLine={false} minTickGap={26} />
        <YAxis tickLine={false} axisLine={false} width={44} unit="ms" />
        <Tooltip content={<TooltipBox formatter={(value) => `${Number(value).toFixed(2)} ms`} />} />
        <Legend
          verticalAlign="top"
          height={22}
          iconType="plainline"
          wrapperStyle={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.12em" }}
        />
        <Line
          type="monotone"
          dataKey="p50_ms"
          name="p50"
          dot={false}
          strokeWidth={1.4}
          stroke={COLORS.info}
        />
        <Line
          type="monotone"
          dataKey="p95_ms"
          name="p95"
          dot={false}
          strokeWidth={1.6}
          stroke={COLORS.signal}
        />
        <Line
          type="monotone"
          dataKey="p99_ms"
          name="p99"
          dot={false}
          strokeWidth={1.4}
          strokeDasharray="4 3"
          stroke={COLORS.crit}
        />
      </LineChart>
    </ChartFrame>
  );
}

/* ------------------------------------------------------------------ drift */
export function DistributionChart({
  bins,
  height = 190,
}: {
  bins: { label: string; baseline: number; current: number }[];
  height?: number;
}) {
  return (
    <ChartFrame height={height}>
      <BarChart data={bins} margin={{ top: 6, right: 6, left: -24, bottom: 0 }} barGap={2}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="label" tickLine={false} axisLine={false} interval="preserveStartEnd" />
        <YAxis
          tickLine={false}
          axisLine={false}
          width={44}
          tickFormatter={(value) => `${(Number(value) * 100).toFixed(0)}%`}
        />
        <Tooltip content={<TooltipBox formatter={(value) => `${(Number(value) * 100).toFixed(2)}%`} />} />
        <Legend
          verticalAlign="top"
          height={22}
          wrapperStyle={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.12em" }}
        />
        <Bar dataKey="baseline" name="baseline" fill={COLORS.faint} radius={[2, 2, 0, 0]} />
        <Bar dataKey="current" name="live" fill={COLORS.signal} radius={[2, 2, 0, 0]} />
      </BarChart>
    </ChartFrame>
  );
}

export function DriftRankChart({
  features,
  warning,
  critical,
  height = 240,
}: {
  features: { name: string; score: number; status: string }[];
  warning: number;
  critical: number;
  height?: number;
}) {
  const data = features.slice(0, 10).map((feature) => ({
    name: feature.name,
    score: Number(feature.score.toFixed(4)),
    status: feature.status,
  }));
  const color = (status: string) =>
    status === "drifted" ? COLORS.crit : status === "warning" ? COLORS.warn : COLORS.ok;
  return (
    <ChartFrame height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, left: 6, bottom: 0 }}>
        <CartesianGrid horizontal={false} />
        <XAxis type="number" tickLine={false} axisLine={false} />
        <YAxis
          type="category"
          dataKey="name"
          width={132}
          tickLine={false}
          axisLine={false}
          interval={0}
        />
        <Tooltip content={<TooltipBox formatter={(value) => `PSI ${value}`} />} />
        <ReferenceLine x={warning} stroke={COLORS.warn} strokeDasharray="3 3" />
        <ReferenceLine x={critical} stroke={COLORS.crit} strokeDasharray="3 3" />
        <Bar dataKey="score" name="PSI" radius={[0, 3, 3, 0]} barSize={12}>
          {data.map((entry) => (
            <Cell key={entry.name} fill={color(entry.status)} />
          ))}
        </Bar>
      </BarChart>
    </ChartFrame>
  );
}

/* ------------------------------------------------------------------ models */
export function RocChart({
  curve,
  auc,
  height = 220,
}: {
  curve: { fpr: number; tpr: number }[];
  auc?: number;
  height?: number;
}) {
  return (
    <ChartFrame height={height}>
      <LineChart data={curve} margin={{ top: 8, right: 10, left: -24, bottom: 0 }}>
        <CartesianGrid />
        <XAxis
          dataKey="fpr"
          type="number"
          domain={[0, 1]}
          tickLine={false}
          axisLine={false}
          tickFormatter={(value) => Number(value).toFixed(1)}
        />
        <YAxis
          type="number"
          domain={[0, 1]}
          tickLine={false}
          axisLine={false}
          width={44}
          tickFormatter={(value) => Number(value).toFixed(1)}
        />
        <Tooltip content={<TooltipBox formatter={(value) => Number(value).toFixed(3)} />} />
        <ReferenceLine
          segment={[
            { x: 0, y: 0 },
            { x: 1, y: 1 },
          ]}
          stroke={COLORS.faint}
          strokeDasharray="3 3"
        />
        <Line
          type="monotone"
          dataKey="tpr"
          name={auc ? `TPR (AUC ${auc.toFixed(4)})` : "TPR"}
          dot={false}
          strokeWidth={1.8}
          stroke={COLORS.signal}
        />
      </LineChart>
    </ChartFrame>
  );
}

export function ImportanceChart({
  importance,
  height = 250,
}: {
  importance: Record<string, number>;
  height?: number;
}) {
  const data = Object.entries(importance)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([name, value]) => ({ name, value: Number((value * 100).toFixed(2)) }));
  return (
    <ChartFrame height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, left: 6, bottom: 0 }}>
        <CartesianGrid horizontal={false} />
        <XAxis type="number" tickLine={false} axisLine={false} unit="%" />
        <YAxis
          type="category"
          dataKey="name"
          width={132}
          tickLine={false}
          axisLine={false}
          interval={0}
        />
        <Tooltip content={<TooltipBox formatter={(value) => `${value}%`} />} />
        <Bar dataKey="value" name="share" fill={COLORS.violet} radius={[0, 3, 3, 0]} barSize={12} />
      </BarChart>
    </ChartFrame>
  );
}

export function ScoreHistogram({
  edges,
  counts,
  height = 180,
}: {
  edges: number[];
  counts: number[];
  height?: number;
}) {
  const total = counts.reduce((sum, value) => sum + value, 0) || 1;
  const data = counts.map((count, index) => ({
    label: edges[index]?.toFixed(2) ?? String(index),
    share: Number((count / total).toFixed(5)),
  }));
  return (
    <ChartFrame height={height}>
      <BarChart data={data} margin={{ top: 6, right: 6, left: -24, bottom: 0 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="label" tickLine={false} axisLine={false} interval={3} />
        <YAxis
          tickLine={false}
          axisLine={false}
          width={44}
          tickFormatter={(value) => `${(Number(value) * 100).toFixed(0)}%`}
        />
        <Tooltip content={<TooltipBox formatter={(value) => `${(Number(value) * 100).toFixed(2)}%`} />} />
        <Bar dataKey="share" name="share" fill={COLORS.info} radius={[2, 2, 0, 0]} />
      </BarChart>
    </ChartFrame>
  );
}

export function Sparkline({
  values,
  tone = "signal",
}: {
  values: number[];
  tone?: keyof typeof COLORS;
}) {
  const data = values.map((value, index) => ({ index, value }));
  return (
    <ChartFrame height={36}>
      <AreaChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id={`spark-${tone}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={COLORS[tone]} stopOpacity={0.45} />
            <stop offset="100%" stopColor={COLORS[tone]} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area
          type="monotone"
          dataKey="value"
          stroke={COLORS[tone]}
          strokeWidth={1.3}
          fill={`url(#spark-${tone})`}
          dot={false}
        />
      </AreaChart>
    </ChartFrame>
  );
}
