"use client";

import { useState } from "react";
import { ChartFrame } from "@/components/charts";
import {
  Button,
  Empty,
  Field,
  KeyValue,
  Notice,
  NumberInput,
  Panel,
  PanelHeader,
  Pill,
  SectionTitle,
  Select,
  Skeleton,
  StatusPill,
  Table,
  Td,
  TextInput,
  Toggle,
} from "@/components/ui";
import { api } from "@/lib/api";
import { ago, duration, int, ms, num, pct, shortId } from "@/lib/format";
import { useAction, usePoll, useSession } from "@/lib/hooks";
import type { LoadTest, ModelEntry, Policy } from "@/lib/types";
import { CartesianGrid, Legend, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";

export default function LoadPage() {
  const { signedIn } = useSession();
  const { data: tests, refresh } = usePoll<LoadTest[]>("/api/loadtests?limit=15", 4000);
  const { data: models } = usePoll<ModelEntry[]>("/api/models", 60000);
  const { data: policies } = usePoll<Policy[]>("/api/policies", 60000);
  const { run, pending, error, notice, setError, setNotice } = useAction();

  const [label, setLabel] = useState("concurrency ramp");
  const [model, setModel] = useState("sim-nano");
  const [policy, setPolicy] = useState("");
  const [levels, setLevels] = useState("1,2,4,8,16,32");
  const [perStage, setPerStage] = useState(40);
  const [maxTokens, setMaxTokens] = useState(140);
  const [measureOverhead, setMeasureOverhead] = useState(true);
  const [picked, setPicked] = useState<string | null>(null);

  const active = tests?.find((t) => t.id === picked) ?? tests?.[0];
  const running = tests?.some((t) => t.status === "running" || t.status === "queued");

  const submit = async () => {
    const parsed = levels
      .split(",")
      .map((value) => Number(value.trim()))
      .filter((value) => Number.isFinite(value) && value > 0);
    await run(
      "submit",
      () =>
        api<LoadTest>("/api/loadtests", {
          method: "POST",
          body: {
            label,
            model: model || undefined,
            policy: policy || undefined,
            concurrency_levels: parsed,
            requests_per_stage: perStage,
            max_tokens: maxTokens,
            measure_tracing_overhead: measureOverhead,
          },
        }),
      "Load test queued",
    );
    refresh();
  };

  const overhead = active?.summary?.tracing_overhead ?? null;

  return (
    <div className="space-y-5">
      <SectionTitle hint="The harness drives the gateway pipeline in process — guard, routing, cache, upstream, accounting — so the numbers describe the gateway rather than uvicorn. Point it at a simulated tier and the ramp is reproducible and free.">
        Load tests
      </SectionTitle>

      <div className="grid gap-4 xl:grid-cols-3">
        <Panel>
          <PanelHeader
            title="New run"
            hint="Ramp concurrency, then optionally measure what tracing costs."
            action={running ? <Pill tone="info" dot>in progress</Pill> : undefined}
          />
          <div className="space-y-3">
            <Field label="Label">
              <TextInput value={label} onChange={setLabel} />
            </Field>
            <Field label="Model" hint="A simulated tier keeps the run free and deterministic.">
              <Select
                value={model}
                onChange={setModel}
                options={[
                  { value: "", label: "let the router choose" },
                  ...(models ?? [])
                    .filter((m) => m.enabled)
                    .map((m) => ({ value: m.slug, label: `${m.slug} · tier ${m.tier}` })),
                ]}
              />
            </Field>
            <Field label="Policy">
              <Select
                value={policy}
                onChange={setPolicy}
                options={[
                  { value: "", label: "active default" },
                  ...(policies ?? []).map((p) => ({ value: p.name, label: p.name })),
                ]}
              />
            </Field>
            <Field label="Concurrency levels" hint="Comma separated, up to 8 stages.">
              <TextInput value={levels} onChange={setLevels} mono />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Requests per stage">
                <NumberInput value={perStage} onChange={setPerStage} min={1} max={500} step={4} />
              </Field>
              <Field label="Max tokens">
                <NumberInput value={maxTokens} onChange={setMaxTokens} min={16} max={2000} step={20} />
              </Field>
            </div>
            <div className="rounded-lg border border-line bg-raised/50 px-3 py-1">
              <Toggle
                checked={measureOverhead}
                onChange={setMeasureOverhead}
                label="Measure tracing overhead"
                hint="Runs the same stage with spans on and off at low concurrency."
              />
            </div>
            {error ? (
              <Notice tone="crit" onDismiss={() => setError(null)}>
                {error}
              </Notice>
            ) : null}
            {notice ? (
              <Notice tone="ok" onDismiss={() => setNotice(null)}>
                {notice}
              </Notice>
            ) : null}
            <Button
              variant="primary"
              className="w-full"
              disabled={!signedIn || running}
              busy={pending === "submit"}
              onClick={() => void submit()}
            >
              Run load test
            </Button>
            {!signedIn ? (
              <p className="text-[11px] text-faint">Sign in to launch runs; results stay public.</p>
            ) : null}
          </div>
        </Panel>

        <Panel className="xl:col-span-2" padded={false}>
          <div className="border-b border-line px-5 py-3">
            <h2 className="text-[13px] font-semibold tracking-tight">History</h2>
          </div>
          <div className="px-5 py-3">
            {!tests ? (
              <Skeleton className="h-28" />
            ) : tests.length ? (
              <Table head={["When", "Label", "Requests", "Peak rps", "Errors", "Duration", "Status"]}>
                {tests.map((test) => (
                  <tr
                    key={test.id}
                    onClick={() => setPicked(test.id)}
                    className={`cursor-pointer transition-colors ${
                      test.id === active?.id ? "bg-signal/6" : "hover:bg-raised/40"
                    }`}
                  >
                    <Td className="text-faint">{ago(test.created_at)}</Td>
                    <Td>
                      {test.label}
                      <span className="num ml-2 text-[10.5px] text-faint">
                        {shortId(test.id, 6)}
                      </span>
                    </Td>
                    <Td mono>{int(test.summary?.requests)}</Td>
                    <Td mono>{num(test.summary?.peak_rps, 2)}</Td>
                    <Td mono>{pct(test.summary?.error_rate ?? 0, 2)}</Td>
                    <Td mono className="text-faint">
                      {duration(test.duration_ms)}
                    </Td>
                    <Td>
                      <StatusPill status={test.status} />
                    </Td>
                  </tr>
                ))}
              </Table>
            ) : (
              <Empty title="No load tests yet" hint="Run one to produce a scaling curve." />
            )}
          </div>
        </Panel>
      </div>

      {active ? (
        <>
          {active.error ? <Notice tone="crit">{active.error}</Notice> : null}

          <div className="grid gap-4 xl:grid-cols-3">
            <Panel className="xl:col-span-2">
              <PanelHeader
                title="Throughput versus concurrency"
                hint="The point where rps stops climbing is the autoscaling threshold."
              />
              {active.stages.length ? (
                <ChartFrame height={240}>
                  <LineChart
                    data={active.stages}
                    margin={{ top: 8, right: 12, left: -20, bottom: 0 }}
                  >
                    <CartesianGrid vertical={false} />
                    <XAxis
                      dataKey="concurrency"
                      tickLine={false}
                      axisLine={false}
                      label={{
                        value: "concurrency",
                        position: "insideBottom",
                        offset: -2,
                        fill: "#596173",
                        fontSize: 10,
                      }}
                    />
                    <YAxis yAxisId="rps" tickLine={false} axisLine={false} width={44} />
                    <YAxis
                      yAxisId="ms"
                      orientation="right"
                      tickLine={false}
                      axisLine={false}
                      width={48}
                      unit="ms"
                    />
                    <Tooltip
                      contentStyle={{
                        background: "#131822",
                        border: "1px solid #262d3a",
                        borderRadius: 10,
                        fontSize: 11,
                      }}
                    />
                    <Legend
                      verticalAlign="top"
                      height={22}
                      iconType="plainline"
                      wrapperStyle={{ fontSize: 10, letterSpacing: "0.1em" }}
                    />
                    <Line
                      yAxisId="rps"
                      type="monotone"
                      dataKey="rps"
                      name="requests/s"
                      stroke="#22d3ee"
                      strokeWidth={1.9}
                      dot={{ r: 2.5 }}
                    />
                    <Line
                      yAxisId="ms"
                      type="monotone"
                      dataKey="ttft_p95"
                      name="TTFT p95"
                      stroke="#fbbf24"
                      strokeWidth={1.5}
                      dot={false}
                    />
                    <Line
                      yAxisId="ms"
                      type="monotone"
                      dataKey="overhead_p50"
                      name="gateway overhead p50"
                      stroke="#fb7185"
                      strokeWidth={1.4}
                      strokeDasharray="4 3"
                      dot={false}
                    />
                  </LineChart>
                </ChartFrame>
              ) : (
                <Empty title="No stages recorded yet" />
              )}
              <p className="mt-2 text-[11px] leading-relaxed text-faint">
                Rising gateway overhead with flat throughput is queueing, not slow inference — the
                signal to add replicas rather than tune the model.
              </p>
            </Panel>

            <Panel>
              <PanelHeader title="Summary" action={<StatusPill status={active.status} />} />
              <KeyValue
                rows={[
                  ["Label", active.label],
                  ["Stages", String(active.summary?.stages ?? active.stages.length)],
                  ["Requests", int(active.summary?.requests)],
                  ["Completed", int(active.summary?.completed)],
                  ["Failed", int(active.summary?.failed)],
                  ["Error rate", pct(active.summary?.error_rate ?? 0, 3)],
                  ["Peak throughput", `${num(active.summary?.peak_rps, 2)} rps`],
                  ["At concurrency", String(active.summary?.peak_rps_concurrency ?? "—")],
                  [
                    "Sustained within SLO",
                    active.summary?.sustained_rps_within_slo
                      ? `${num(active.summary.sustained_rps_within_slo, 2)} rps @ c${active.summary.sustained_concurrency}`
                      : "—",
                  ],
                  ["SLO target", ms(active.summary?.slo_ttft_ms ?? 0)],
                  ["Tokens", int(active.summary?.tokens)],
                  ["Cost", `$${num(active.summary?.cost_usd, 6)}`],
                  ["Duration", duration(active.duration_ms)],
                ]}
              />
            </Panel>
          </div>

          <div className="grid gap-4 xl:grid-cols-3">
            <Panel className="xl:col-span-2" padded={false}>
              <div className="border-b border-line px-5 py-3">
                <h2 className="text-[13px] font-semibold tracking-tight">Stage detail</h2>
              </div>
              <div className="px-5 py-3">
                <Table
                  head={[
                    "Concurrency",
                    "rps",
                    "ok/fail",
                    "TTFT p50",
                    "TTFT p95",
                    "Latency p95",
                    "Overhead p50",
                    "Peak in flight",
                  ]}
                >
                  {active.stages.map((stage) => (
                    <tr key={stage.concurrency}>
                      <Td mono>{stage.concurrency}</Td>
                      <Td mono className="text-signal">
                        {num(stage.rps, 2)}
                      </Td>
                      <Td mono>
                        {stage.completed}/{stage.failed}
                      </Td>
                      <Td mono>{ms(stage.ttft_p50)}</Td>
                      <Td mono>{ms(stage.ttft_p95)}</Td>
                      <Td mono>{ms(stage.latency_p95)}</Td>
                      <Td mono className={stage.overhead_p50 > 50 ? "text-warn" : ""}>
                        {ms(stage.overhead_p50)}
                      </Td>
                      <Td mono className="text-faint">
                        {stage.peak_inflight}
                      </Td>
                    </tr>
                  ))}
                </Table>
              </div>
            </Panel>

            <Panel>
              <PanelHeader
                title="Tracing overhead"
                hint={overhead?.metric ?? "Enable the measurement to get a number here."}
              />
              {overhead ? (
                <>
                  <div className="mb-3 rounded-xl border border-signal/25 bg-signal/[0.05] p-3">
                    <p className="label-xs">added gateway overhead</p>
                    <p className="num mt-1 text-2xl font-semibold text-signal">
                      {overhead.delta_ms >= 0 ? "+" : ""}
                      {num(overhead.delta_ms, 2)} ms
                    </p>
                    <p className="mt-1 text-[11px] text-faint">
                      {pct(overhead.overhead_ratio, 1)} of the untraced overhead, measured at
                      concurrency {overhead.concurrency} over {overhead.requests_per_arm} calls per
                      arm
                    </p>
                  </div>
                  <KeyValue
                    rows={[
                      ["Overhead p50, traced", ms(overhead.overhead_p50_with_tracing_ms)],
                      ["Overhead p50, untraced", ms(overhead.overhead_p50_without_tracing_ms)],
                      ["Overhead p95, traced", ms(overhead.overhead_p95_with_tracing_ms)],
                      ["Overhead p95, untraced", ms(overhead.overhead_p95_without_tracing_ms)],
                      ["End-to-end p50, traced", ms(overhead.latency_p50_with_tracing_ms)],
                      ["End-to-end p50, untraced", ms(overhead.latency_p50_without_tracing_ms)],
                      ["rps traced", num(overhead.rps_with_tracing, 2)],
                      ["rps untraced", num(overhead.rps_without_tracing, 2)],
                    ]}
                  />
                  <p className="mt-2 text-[10.5px] leading-relaxed text-faint">{overhead.note}</p>
                </>
              ) : (
                <Empty title="Not measured in this run" />
              )}
            </Panel>
          </div>
        </>
      ) : null}
    </div>
  );
}
