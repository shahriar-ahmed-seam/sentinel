"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import {
  Button,
  Code,
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
  Toggle,
} from "@/components/ui";
import { API_BASE, getToken, url } from "@/lib/api";
import { ms, num, pct } from "@/lib/format";
import { usePoll, useSession } from "@/lib/hooks";
import type { ModelEntry, Policy } from "@/lib/types";

type SentinelMeta = {
  request_id?: string;
  trace_id?: string;
  model?: string;
  provider?: string;
  policy?: string;
  strategy?: string;
  routing_reason?: string;
  complexity?: string;
  cache?: string;
  cost_usd?: number;
  baseline_cost_usd?: number;
  saved_usd?: number;
  ttft_ms?: number;
  latency_ms?: number;
  gateway_overhead_ms?: number;
  tokens_per_second?: number;
  guard_flags?: string[];
};

type Turn = {
  role: "user" | "assistant";
  content: string;
  reasoning?: string;
  meta?: SentinelMeta;
  usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
  error?: string;
};

export default function PlaygroundPage() {
  const { signedIn } = useSession();
  const { data: models } = usePoll<ModelEntry[]>("/api/models", 60000);
  const { data: policies } = usePoll<Policy[]>("/api/policies", 60000);

  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState(
    "Explain step by step why a p99 latency spike can hide behind a healthy p50, then suggest two mitigations.",
  );
  const [model, setModel] = useState("");
  const [policy, setPolicy] = useState("");
  const [temperature, setTemperature] = useState(0.2);
  const [maxTokens, setMaxTokens] = useState(400);
  const [streaming, setStreaming] = useState(true);
  const [cacheMode, setCacheMode] = useState<"auto" | "on" | "off">("auto");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const routableModels = (models ?? []).filter((m) => m.enabled);
  const last = turns[turns.length - 1];

  const send = async () => {
    const prompt = input.trim();
    if (!prompt || busy) return;
    setError(null);
    setBusy(true);
    setInput("");

    const history = [...turns, { role: "user" as const, content: prompt }];
    setTurns([...history, { role: "assistant", content: "" }]);

    const controller = new AbortController();
    abortRef.current = controller;

    const body = {
      messages: history.map((t) => ({ role: t.role, content: t.content })),
      model: model || undefined,
      policy: policy || undefined,
      temperature,
      max_tokens: maxTokens,
      stream: streaming,
      cache: cacheMode === "auto" ? undefined : cacheMode === "on",
    };

    const headers: Record<string, string> = { "content-type": "application/json" };
    const token = getToken();
    if (token) headers.authorization = `Bearer ${token}`;

    try {
      const response = await fetch(url("/v1/chat/completions"), {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      if (!streaming) {
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.detail?.message ?? "request failed");
        applyFinal(payload);
        return;
      }

      if (!response.ok || !response.body) {
        const text = await response.text();
        throw new Error(text.slice(0, 300) || `HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          const line = frame.split("\n").find((l) => l.startsWith("data:"));
          if (!line) continue;
          const raw = line.slice(5).trim();
          if (raw === "[DONE]") continue;
          let event: Record<string, unknown>;
          try {
            event = JSON.parse(raw);
          } catch {
            continue;
          }
          if (event.error) {
            throw new Error(String((event.error as { message?: string }).message ?? "gateway error"));
          }
          applyChunk(event);
        }
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        setTurns((current) => patchLast(current, { error: "cancelled" }));
      } else {
        const message = err instanceof Error ? err.message : "request failed";
        setError(message);
        setTurns((current) => patchLast(current, { error: message }));
      }
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  };

  const applyChunk = (event: Record<string, unknown>) => {
    const choices = (event.choices as { delta?: Record<string, string> }[] | undefined) ?? [];
    const delta = choices[0]?.delta ?? {};
    const meta = event.sentinel as SentinelMeta | undefined;
    const usage = event.usage as Turn["usage"] | undefined;

    setTurns((current) => {
      const next = [...current];
      const target = next[next.length - 1];
      if (!target || target.role !== "assistant") return current;
      next[next.length - 1] = {
        ...target,
        content: target.content + (delta.content ?? ""),
        reasoning: (target.reasoning ?? "") + (delta.reasoning_content ?? ""),
        meta: meta ? { ...target.meta, ...meta } : target.meta,
        usage: usage ?? target.usage,
      };
      return next;
    });
  };

  const applyFinal = (payload: Record<string, unknown>) => {
    const choices = (payload.choices as { message?: { content?: string } }[] | undefined) ?? [];
    setTurns((current) =>
      patchLast(current, {
        content: choices[0]?.message?.content ?? "",
        meta: payload.sentinel as SentinelMeta,
        usage: payload.usage as Turn["usage"],
      }),
    );
  };

  const curl = `curl -N ${API_BASE || "https://<gateway-host>"}/v1/chat/completions \\
  -H "content-type: application/json" \\
  -H "authorization: Bearer $SENTINEL_API_KEY" \\
  -d '{"messages":[{"role":"user","content":"..."}],"stream":true${policy ? `,"policy":"${policy}"` : ""}}'`;

  return (
    <div className="space-y-5">
      <SectionTitle hint="This talks to the same public endpoint any OpenAI client would use. Each answer carries the routing decision, cost against the premium baseline and a trace id you can open.">
        Playground
      </SectionTitle>

      <div className="grid gap-4 xl:grid-cols-5">
        <div className="space-y-4 xl:col-span-3">
          <Panel padded={false}>
            <div className="flex items-center justify-between border-b border-line px-5 py-3">
              <h2 className="text-[13px] font-semibold tracking-tight">Conversation</h2>
              <div className="flex items-center gap-2">
                {busy ? (
                  <Button size="sm" variant="danger" onClick={() => abortRef.current?.abort()}>
                    Stop
                  </Button>
                ) : null}
                {turns.length ? (
                  <Button size="sm" variant="ghost" onClick={() => setTurns([])}>
                    Clear
                  </Button>
                ) : null}
              </div>
            </div>

            <div className="max-h-[520px] space-y-4 overflow-y-auto px-5 py-4">
              {turns.length === 0 ? (
                <Empty
                  title="No messages yet"
                  hint="Send something short, then something demanding — the router should pick different tiers."
                />
              ) : (
                turns.map((turn, index) => (
                  <div key={index} className="space-y-1.5">
                    <div className="flex items-center gap-2">
                      <Pill tone={turn.role === "user" ? "neutral" : "signal"}>{turn.role}</Pill>
                      {turn.meta?.model ? (
                        <span className="num text-[10.5px] text-faint">
                          {turn.meta.model} · {turn.meta.provider}
                          {turn.meta.cache === "hit" ? " · cache hit" : ""}
                        </span>
                      ) : null}
                    </div>
                    {turn.reasoning ? (
                      <details className="rounded-lg border border-violet/25 bg-violet/[0.04] px-2.5 py-1.5">
                        <summary className="label-xs cursor-pointer select-none">
                          reasoning trace
                        </summary>
                        <pre className="mt-1.5 max-h-40 overflow-auto whitespace-pre-wrap text-[11px] leading-relaxed text-violet/80">
                          {turn.reasoning}
                        </pre>
                      </details>
                    ) : null}
                    <div
                      className={`whitespace-pre-wrap rounded-xl border px-3 py-2.5 text-[13px] leading-relaxed ${
                        turn.role === "user"
                          ? "border-line bg-raised/60 text-ink"
                          : "border-signal/20 bg-signal/[0.04] text-ink"
                      } ${busy && index === turns.length - 1 && !turn.content ? "caret" : ""}`}
                    >
                      {turn.content || (turn.error ? "" : busy ? "" : "(empty response)")}
                      {turn.error ? <span className="text-crit">{turn.error}</span> : null}
                    </div>
                    {turn.meta && turn.role === "assistant" ? (
                      <div className="flex flex-wrap gap-1.5 text-[10.5px]">
                        <Tag>{turn.meta.complexity ?? "?"}</Tag>
                        <Tag>{turn.meta.policy ?? "?"}</Tag>
                        <Tag>ttft {ms(turn.meta.ttft_ms ?? 0)}</Tag>
                        <Tag>{num(turn.meta.tokens_per_second ?? 0, 0)} tok/s</Tag>
                        <Tag>${num(turn.meta.cost_usd ?? 0, 6)}</Tag>
                        {turn.meta.saved_usd ? (
                          <Tag tone="text-signal">saved ${num(turn.meta.saved_usd, 6)}</Tag>
                        ) : null}
                        {turn.meta.trace_id ? (
                          <Link
                            href={`/console/traces/${turn.meta.trace_id}`}
                            className="num rounded border border-line bg-raised px-1.5 py-0.5 text-muted transition-colors hover:text-signal"
                          >
                            trace →
                          </Link>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                ))
              )}
            </div>

            <div className="space-y-2 border-t border-line px-5 py-4">
              {error ? (
                <Notice tone="crit" onDismiss={() => setError(null)}>
                  {error}
                </Notice>
              ) : null}
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) void send();
                }}
                rows={3}
                placeholder="Ask something. Cmd/Ctrl+Enter to send."
                className="w-full resize-y rounded-lg border border-line-strong bg-raised px-3 py-2 text-[13px] leading-relaxed text-ink placeholder:text-faint focus:border-signal/60 focus:outline-none"
              />
              <div className="flex items-center justify-between gap-2">
                <p className="text-[10.5px] text-faint">
                  {signedIn
                    ? "Sending as the operator token."
                    : "Sending anonymously — allowed on this demo."}
                </p>
                <Button variant="primary" busy={busy} onClick={() => void send()}>
                  Send
                </Button>
              </div>
            </div>
          </Panel>

          <Panel>
            <PanelHeader title="Same call from a client" hint="Any OpenAI SDK works unchanged." />
            <pre className="num overflow-x-auto rounded-lg border border-line bg-base p-3 text-[10.5px] leading-relaxed text-muted">
              {curl}
            </pre>
            <p className="mt-2 text-[11px] leading-relaxed text-faint">
              Extra fields <Code>policy</Code>, <Code>cache</Code> and <Code>capabilities</Code> are
              additive; the response adds a <Code>sentinel</Code> block. Standard clients ignore both.
            </p>
          </Panel>
        </div>

        <div className="space-y-4 xl:col-span-2">
          <Panel>
            <PanelHeader title="Request options" />
            <div className="space-y-3">
              <Field label="Model" hint="Leave on router to let the policy decide.">
                <Select
                  value={model}
                  onChange={setModel}
                  options={[
                    { value: "", label: "let the router choose" },
                    ...routableModels.map((m) => ({
                      value: m.slug,
                      label: `${m.slug} · tier ${m.tier}`,
                    })),
                  ]}
                />
              </Field>
              <Field label="Policy">
                <Select
                  value={policy}
                  onChange={setPolicy}
                  options={[
                    { value: "", label: "active default" },
                    ...(policies ?? []).map((p) => ({
                      value: p.name,
                      label: `${p.name}${p.is_default ? " (default)" : ""}`,
                    })),
                  ]}
                />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Temperature">
                  <NumberInput
                    value={temperature}
                    onChange={setTemperature}
                    min={0}
                    max={2}
                    step={0.1}
                  />
                </Field>
                <Field label="Max tokens">
                  <NumberInput value={maxTokens} onChange={setMaxTokens} min={16} max={4000} step={50} />
                </Field>
              </div>
              <Field label="Cache" hint="Auto caches only low-temperature calls.">
                <Select
                  value={cacheMode}
                  onChange={setCacheMode}
                  options={[
                    { value: "auto", label: "auto (policy decides)" },
                    { value: "on", label: "force cache on" },
                    { value: "off", label: "force cache off" },
                  ]}
                />
              </Field>
              <div className="rounded-lg border border-line bg-raised/50 px-3 py-1">
                <Toggle
                  checked={streaming}
                  onChange={setStreaming}
                  label="Stream tokens"
                  hint="Server-sent events, identical framing to OpenAI."
                />
              </div>
            </div>
          </Panel>

          {last?.meta ? (
            <Panel>
              <PanelHeader
                title="Last call"
                hint={last.meta.routing_reason}
                action={
                  <Pill tone={last.meta.cache === "hit" ? "ok" : "neutral"}>
                    {last.meta.cache ?? "—"}
                  </Pill>
                }
              />
              <KeyValue
                rows={[
                  ["Model", last.meta.model ?? "—"],
                  ["Provider", last.meta.provider ?? "—"],
                  ["Policy", `${last.meta.policy ?? "—"} (${last.meta.strategy ?? "—"})`],
                  ["Complexity", last.meta.complexity ?? "—"],
                  [
                    "Tokens",
                    last.usage
                      ? `${last.usage.prompt_tokens} / ${last.usage.completion_tokens}`
                      : "—",
                  ],
                  ["Cost", `$${num(last.meta.cost_usd ?? 0, 8)}`],
                  ["Baseline", `$${num(last.meta.baseline_cost_usd ?? 0, 8)}`],
                  [
                    "Avoided",
                    last.meta.baseline_cost_usd
                      ? `$${num(last.meta.saved_usd ?? 0, 8)} (${pct(
                          (last.meta.saved_usd ?? 0) / last.meta.baseline_cost_usd,
                          1,
                        )})`
                      : "—",
                  ],
                  ["TTFT", ms(last.meta.ttft_ms ?? 0)],
                  ["End to end", ms(last.meta.latency_ms ?? 0)],
                  ["Gateway overhead", ms(last.meta.gateway_overhead_ms ?? 0)],
                  ["Throughput", `${num(last.meta.tokens_per_second ?? 0, 1)} tok/s`],
                ]}
              />
              {last.meta.guard_flags?.length ? (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {last.meta.guard_flags.map((flag) => (
                    <Pill key={flag} tone="warn">
                      {flag}
                    </Pill>
                  ))}
                </div>
              ) : null}
            </Panel>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function Tag({ children, tone = "text-muted" }: { children: React.ReactNode; tone?: string }) {
  return (
    <span className={`num rounded border border-line bg-raised px-1.5 py-0.5 ${tone}`}>
      {children}
    </span>
  );
}

function patchLast(turns: Turn[], patch: Partial<Turn>): Turn[] {
  if (!turns.length) return turns;
  const next = [...turns];
  next[next.length - 1] = { ...next[next.length - 1], ...patch };
  return next;
}
