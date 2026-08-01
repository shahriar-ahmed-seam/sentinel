"use client";

import Link from "next/link";
import { useState } from "react";
import {
  Bar,
  Button,
  Empty,
  Field,
  NumberInput,
  Notice,
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
import { api } from "@/lib/api";
import { ms, num, pct } from "@/lib/format";
import { useAction, usePoll, useSession } from "@/lib/hooks";
import type { Explanation, ModelEntry, Policy } from "@/lib/types";

const SAMPLES = [
  "hey",
  "What is the difference between a rate limit and a quota?",
  "Explain step by step how to choose between a read replica and a cache for a read-heavy endpoint, and analyse the failure modes of each.",
  "Derive the closed form, prove the complexity bound step by step, then optimise the algorithm and analyse the trade-offs across the memory hierarchy with worked examples.",
];

export default function RoutingPage() {
  const { signedIn } = useSession();
  const { data: policies, refresh } = usePoll<Policy[]>("/api/policies", 20000);
  const { data: models } = usePoll<ModelEntry[]>("/api/models", 30000);
  const { run, pending, error, notice, setError, setNotice } = useAction();

  const [prompt, setPrompt] = useState(SAMPLES[2]);
  const [policyName, setPolicyName] = useState("");
  const [expectedOutput, setExpectedOutput] = useState(400);
  const [explanation, setExplanation] = useState<Explanation | null>(null);

  const explain = async () => {
    const result = await run("explain", () =>
      api<Explanation>("/api/policies/explain", {
        method: "POST",
        body: {
          prompt,
          policy: policyName || undefined,
          expected_output_tokens: expectedOutput,
        },
      }),
    );
    if (result) setExplanation(result);
  };

  const makeDefault = async (name: string) => {
    await run(`default-${name}`, () => api(`/api/policies/${name}/default`, { method: "POST" }), `${name} is now the default`);
    refresh();
  };

  const routable = new Set(
    (models ?? []).filter((m) => m.enabled).map((m) => m.slug),
  );

  return (
    <div className="space-y-5">
      <SectionTitle hint="A prompt is classified by a rule-based scorer, then the active policy picks a model. Paying an LLM to decide which LLM to pay is a bad trade at the hot path, so the classifier is cheap and auditable — and this page lets you dry-run it without spending anything.">
        Routing
      </SectionTitle>

      <div className="grid gap-4 xl:grid-cols-5">
        <Panel className="xl:col-span-2">
          <PanelHeader
            title="Dry-run the router"
            hint="No upstream is called and nothing is billed."
          />
          <div className="space-y-3">
            <Field label="Prompt">
              <textarea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                rows={6}
                className="w-full resize-y rounded-lg border border-line-strong bg-raised px-3 py-2 text-[12.5px] leading-relaxed text-ink placeholder:text-faint focus:border-signal/60 focus:outline-none"
              />
            </Field>
            <div className="flex flex-wrap gap-1.5">
              {SAMPLES.map((sample, index) => (
                <button
                  key={index}
                  type="button"
                  onClick={() => setPrompt(sample)}
                  className="rounded-md border border-line bg-raised px-2 py-1 text-[10.5px] text-muted transition-colors hover:text-ink"
                >
                  sample {index + 1}
                </button>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Policy">
                <Select
                  value={policyName}
                  onChange={setPolicyName}
                  options={[
                    { value: "", label: "active default" },
                    ...(policies ?? []).map((p) => ({ value: p.name, label: p.name })),
                  ]}
                />
              </Field>
              <Field label="Expected output tokens">
                <NumberInput
                  value={expectedOutput}
                  onChange={setExpectedOutput}
                  min={16}
                  max={8000}
                  step={50}
                />
              </Field>
            </div>
            {error ? (
              <Notice tone="crit" onDismiss={() => setError(null)}>
                {error}
              </Notice>
            ) : null}
            <Button
              variant="primary"
              className="w-full"
              busy={pending === "explain"}
              onClick={() => void explain()}
            >
              Explain the decision
            </Button>
          </div>
        </Panel>

        <Panel className="xl:col-span-3">
          <PanelHeader
            title="Decision"
            hint={explanation ? explanation.reason : "Run the explainer to see the candidate set."}
            action={
              explanation ? (
                <div className="flex items-center gap-2">
                  <Pill tone="info">{explanation.complexity}</Pill>
                  <Pill tone="neutral">tier ≥ {explanation.required_tier}</Pill>
                </div>
              ) : undefined
            }
          />
          {explanation ? (
            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-4">
                <Metric label="chosen" value={explanation.chosen.slug} />
                <Metric label="estimated cost" value={`$${num(explanation.chosen.estimated_cost_usd, 6)}`} />
                <Metric label="estimated latency" value={ms(explanation.chosen.estimated_latency_ms)} />
                <Metric
                  label="vs baseline"
                  value={
                    explanation.baseline
                      ? `${pct(explanation.baseline.saving_ratio, 1)} cheaper`
                      : "—"
                  }
                />
              </div>

              <Table head={["Candidate", "Provider", "Tier", "Est. cost", "Est. latency", "Circuit"]}>
                {explanation.considered.map((candidate) => (
                  <tr
                    key={candidate.slug}
                    className={candidate.slug === explanation.chosen.slug ? "bg-signal/6" : undefined}
                  >
                    <Td mono>
                      {candidate.slug}
                      {candidate.slug === explanation.chosen.slug ? (
                        <span className="ml-2 text-[10px] text-signal">chosen</span>
                      ) : null}
                    </Td>
                    <Td className="text-muted">{candidate.provider}</Td>
                    <Td mono className={candidate.meets_tier ? "" : "text-faint"}>
                      {candidate.tier}
                      {candidate.meets_tier ? "" : " ↓"}
                    </Td>
                    <Td mono>${num(candidate.estimated_cost_usd, 6)}</Td>
                    <Td mono>{ms(candidate.estimated_latency_ms)}</Td>
                    <Td>
                      <StatusPill status={candidate.circuit === "closed" ? "live" : candidate.circuit} />
                    </Td>
                  </tr>
                ))}
              </Table>

              <div className="flex flex-wrap items-center gap-2 text-[11px] text-faint">
                <span>fallback chain:</span>
                {explanation.fallbacks.length ? (
                  explanation.fallbacks.map((slug) => (
                    <Pill key={slug} tone="neutral">
                      {slug}
                    </Pill>
                  ))
                ) : (
                  <span>none configured</span>
                )}
                {explanation.shadow ? (
                  <>
                    <span className="ml-2">shadow:</span>
                    <Pill tone="violet">{explanation.shadow}</Pill>
                  </>
                ) : null}
              </div>
            </div>
          ) : (
            <Empty
              title="No decision yet"
              hint="Try sample 1 and sample 4 back to back — they should land on different tiers."
            />
          )}
        </Panel>
      </div>

      {notice ? (
        <Notice tone="ok" onDismiss={() => setNotice(null)}>
          {notice}
        </Notice>
      ) : null}

      <Panel padded={false}>
        <div className="flex items-center justify-between border-b border-line px-5 py-3">
          <h2 className="text-[13px] font-semibold tracking-tight">Policies</h2>
          <Link
            href="/console/models"
            className="text-[11px] text-muted transition-colors hover:text-signal"
          >
            price book →
          </Link>
        </div>
        <div className="space-y-3 px-5 py-4">
          {!policies ? (
            <Skeleton className="h-32" />
          ) : (
            policies.map((policy) => (
              <div key={policy.id} className="rounded-xl border border-line bg-raised/40 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="num text-[13.5px] font-medium text-ink">{policy.name}</span>
                      <Pill tone="info">{policy.strategy.replace(/_/g, " ")}</Pill>
                      {policy.is_default ? <Pill tone="signal">default</Pill> : null}
                      {!policy.enabled ? <Pill tone="neutral">disabled</Pill> : null}
                    </div>
                    <p className="mt-1 max-w-2xl text-[12px] leading-relaxed text-muted">
                      {policy.description}
                    </p>
                  </div>
                  {signedIn && !policy.is_default ? (
                    <Button
                      size="sm"
                      busy={pending === `default-${policy.name}`}
                      onClick={() => void makeDefault(policy.name)}
                    >
                      Make default
                    </Button>
                  ) : null}
                </div>

                <div className="mt-3 grid gap-3 lg:grid-cols-3">
                  <div>
                    <p className="label-xs mb-1.5">candidates</p>
                    <div className="flex flex-wrap gap-1.5">
                      {policy.candidates.length ? (
                        policy.candidates.map((slug) => (
                          <Pill key={slug} tone={routable.has(slug) ? "neutral" : "warn"}>
                            {slug}
                            {routable.has(slug) ? "" : " (unroutable)"}
                          </Pill>
                        ))
                      ) : (
                        <span className="text-[11px] text-faint">whole catalogue</span>
                      )}
                    </div>
                  </div>
                  <div>
                    <p className="label-xs mb-1.5">fallbacks</p>
                    <div className="flex flex-wrap gap-1.5">
                      {policy.fallbacks.length ? (
                        policy.fallbacks.map((slug) => (
                          <Pill key={slug} tone="neutral">
                            {slug}
                          </Pill>
                        ))
                      ) : (
                        <span className="text-[11px] text-faint">implicit cross-provider</span>
                      )}
                    </div>
                  </div>
                  <div>
                    <p className="label-xs mb-1.5">shadow</p>
                    {policy.shadow_model ? (
                      <div className="flex items-center gap-2">
                        <Pill tone="violet">{policy.shadow_model}</Pill>
                        <span className="num text-[11px] text-faint">
                          {pct(policy.shadow_sample_rate, 0)} of calls
                        </span>
                      </div>
                    ) : (
                      <span className="text-[11px] text-faint">off</span>
                    )}
                  </div>
                </div>

                {policy.strategy === "weighted" && Object.keys(policy.weights).length ? (
                  <div className="mt-3 space-y-1.5">
                    <p className="label-xs">traffic split</p>
                    {Object.entries(policy.weights).map(([slug, weight]) => {
                      const total = Object.values(policy.weights).reduce((a, b) => a + b, 0) || 1;
                      return (
                        <div key={slug}>
                          <div className="flex items-baseline justify-between text-[11.5px]">
                            <span className="num text-muted">{slug}</span>
                            <span className="num text-ink">{pct(weight / total, 0)}</span>
                          </div>
                          <Bar value={weight / total} tone="signal" />
                        </div>
                      );
                    })}
                  </div>
                ) : null}
              </div>
            ))
          )}
        </div>
      </Panel>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line bg-raised/50 px-2.5 py-2">
      <p className="label-xs">{label}</p>
      <p className="num mt-1 truncate text-[13.5px] text-ink">{value}</p>
    </div>
  );
}
