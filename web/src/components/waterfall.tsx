"use client";

import clsx from "clsx";
import { useState } from "react";
import { ms } from "@/lib/format";
import type { Span } from "@/lib/types";

const KIND_TONE: Record<string, string> = {
  server: "bg-signal",
  client: "bg-violet",
  internal: "bg-info",
};

type Node = { span: Span; depth: number };

/** Order spans as a tree, then render each as an offset bar on a shared axis. */
function flatten(spans: Span[]): Node[] {
  const byParent = new Map<string | null, Span[]>();
  for (const span of spans) {
    const key = span.parent_id ?? null;
    byParent.set(key, [...(byParent.get(key) ?? []), span]);
  }
  const known = new Set(spans.map((s) => s.id));
  const roots = spans.filter((s) => !s.parent_id || !known.has(s.parent_id));
  const out: Node[] = [];

  const walk = (span: Span, depth: number) => {
    out.push({ span, depth });
    const children = (byParent.get(span.id) ?? []).sort(
      (a, b) => new Date(a.started_at).getTime() - new Date(b.started_at).getTime(),
    );
    for (const child of children) walk(child, depth + 1);
  };
  for (const root of roots.sort(
    (a, b) => new Date(a.started_at).getTime() - new Date(b.started_at).getTime(),
  )) {
    walk(root, 0);
  }
  return out;
}

export function TraceWaterfall({ spans }: { spans: Span[] }) {
  const [selected, setSelected] = useState<string | null>(null);
  if (!spans.length) return null;

  const nodes = flatten(spans);
  const origin = Math.min(...spans.map((s) => new Date(s.started_at).getTime()));
  const end = Math.max(
    ...spans.map((s) => new Date(s.ended_at ?? s.started_at).getTime() + (s.ended_at ? 0 : s.duration_ms)),
  );
  const total = Math.max(end - origin, 1);
  const active = spans.find((s) => s.id === selected);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-[10.5px] text-faint">
        <span>0ms</span>
        <span>{ms(total / 2)}</span>
        <span>{ms(total)}</span>
      </div>

      <ol className="space-y-1">
        {nodes.map(({ span, depth }) => {
          const start = new Date(span.started_at).getTime() - origin;
          const left = (start / total) * 100;
          const width = Math.max(0.6, (span.duration_ms / total) * 100);
          const isSelected = selected === span.id;
          return (
            <li key={span.id}>
              <button
                type="button"
                onClick={() => setSelected(isSelected ? null : span.id)}
                className={clsx(
                  "group grid w-full grid-cols-[minmax(140px,220px)_1fr_70px] items-center gap-3 rounded-md px-1.5 py-1 text-left transition-colors",
                  isSelected ? "bg-signal/8" : "hover:bg-raised/60",
                )}
              >
                <span
                  className="num truncate text-[11.5px] text-muted"
                  style={{ paddingLeft: `${depth * 12}px` }}
                >
                  {span.name}
                </span>
                <span className="relative h-4 rounded bg-line/60">
                  <span
                    className={clsx(
                      "absolute top-0.5 h-3 rounded-sm",
                      span.status === "error" ? "bg-crit" : KIND_TONE[span.kind] ?? "bg-info",
                    )}
                    style={{ left: `${left}%`, width: `${width}%` }}
                  />
                  {span.events.map((event) => (
                    <span
                      key={event.name + event.offset_ms}
                      title={`${event.name} @ ${event.offset_ms.toFixed(1)}ms`}
                      className="absolute top-0 h-4 w-px bg-warn"
                      style={{
                        left: `${((start + event.offset_ms) / total) * 100}%`,
                      }}
                    />
                  ))}
                </span>
                <span className="num text-right text-[11px] text-faint">
                  {ms(span.duration_ms)}
                </span>
              </button>
            </li>
          );
        })}
      </ol>

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-2 text-[10.5px] text-faint">
        <Legend tone="bg-signal" label="server" />
        <Legend tone="bg-info" label="internal" />
        <Legend tone="bg-violet" label="upstream" />
        <Legend tone="bg-crit" label="error" />
        <Legend tone="bg-warn" label="event marker" />
      </div>

      {active ? (
        <div className="rounded-xl border border-line bg-raised/50 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="num text-[12.5px] text-ink">{active.name}</p>
            <p className="num text-[11px] text-faint">
              {active.kind} · {ms(active.duration_ms)} · span {active.id}
            </p>
          </div>
          {Object.keys(active.attributes ?? {}).length ? (
            <dl className="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-2">
              {Object.entries(active.attributes).map(([key, value]) => (
                <div key={key} className="flex items-baseline justify-between gap-3 text-[11.5px]">
                  <dt className="text-faint">{key}</dt>
                  <dd className="num max-w-[60%] truncate text-right text-muted">
                    {String(value)}
                  </dd>
                </div>
              ))}
            </dl>
          ) : null}
          {active.events.length ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {active.events.map((event) => (
                <span
                  key={event.name + event.offset_ms}
                  className="num rounded border border-warn/30 bg-warn/10 px-1.5 py-0.5 text-[10.5px] text-warn"
                >
                  {event.name} @ {event.offset_ms.toFixed(1)}ms
                </span>
              ))}
            </div>
          ) : null}
        </div>
      ) : (
        <p className="text-[11px] text-faint">Select a span to inspect its attributes.</p>
      )}
    </div>
  );
}

function Legend({ tone, label }: { tone: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <i className={clsx("size-2 rounded-sm", tone)} />
      {label}
    </span>
  );
}
