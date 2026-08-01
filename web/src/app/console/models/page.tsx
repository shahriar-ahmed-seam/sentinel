"use client";

import { useState } from "react";
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
  Skeleton,
  Table,
  Td,
  Toggle,
} from "@/components/ui";
import { api } from "@/lib/api";
import { ago, int, ms, num, stamp } from "@/lib/format";
import { useAction, usePoll, useSession } from "@/lib/hooks";
import type { ModelEntry } from "@/lib/types";

type Routable = {
  providers: Record<string, { live: boolean }>;
  models: {
    slug: string;
    provider: string;
    tier: number;
    enabled: boolean;
    provider_configured: boolean;
    routable: boolean;
    blocked_reason: string;
  }[];
};

const TIER_LABEL: Record<number, string> = {
  1: "trivial",
  2: "standard",
  3: "complex",
  4: "frontier",
};

export default function CatalogPage() {
  const { signedIn } = useSession();
  const { data: models, refresh } = usePoll<ModelEntry[]>("/api/models", 20000);
  const { data: routable } = usePoll<Routable>("/api/models/routable", 20000);
  const { run, pending, error, notice, setError, setNotice } = useAction();
  const [picked, setPicked] = useState<string | null>(null);

  const active = models?.find((m) => m.slug === picked) ?? models?.[0];
  const [draft, setDraft] = useState<Partial<ModelEntry>>({});

  // Derived: server row with unsaved edits layered on top.
  const edited = active ? { ...active, ...draft } : null;
  const dirty = Object.keys(draft).length > 0;

  const select = (slug: string) => {
    setPicked(slug);
    setDraft({});
  };

  const save = async () => {
    if (!edited || !active) return;
    await run(
      "save",
      () =>
        api(`/api/models/${active.slug}`, {
          method: "PATCH",
          body: { ...draft, mark_price_verified: true },
        }),
      `${active.slug} updated`,
    );
    setDraft({});
    refresh();
  };

  const toggle = async (model: ModelEntry) => {
    await run(
      `toggle-${model.slug}`,
      () =>
        api(`/api/models/${model.slug}`, {
          method: "PATCH",
          body: { enabled: !model.enabled },
        }),
      `${model.slug} ${model.enabled ? "disabled" : "enabled"}`,
    );
    refresh();
  };

  const blocked = new Map(
    (routable?.models ?? []).map((m) => [m.slug, m.blocked_reason] as const),
  );

  return (
    <div className="space-y-5">
      <SectionTitle hint="The catalogue is the price book and the capability map in one place. The router reads these rows, so every cost figure in the dashboard traces back to a number you can edit here rather than a constant buried in code.">
        Model catalogue
      </SectionTitle>

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

      {routable ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="label-xs">providers configured:</span>
          {Object.entries(routable.providers).map(([name, info]) => (
            <Pill key={name} tone={info.live ? "ok" : "neutral"} dot>
              {name} {info.live ? "(live)" : "(local)"}
            </Pill>
          ))}
        </div>
      ) : null}

      <Panel padded={false}>
        <div className="border-b border-line px-5 py-3">
          <h2 className="text-[13px] font-semibold tracking-tight">Routable models</h2>
        </div>
        <div className="px-5 py-3">
          {!models ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-9" />
              ))}
            </div>
          ) : (
            <Table
              head={[
                "Model",
                "Provider",
                "Tier",
                "In $/Mtok",
                "Out $/Mtok",
                "Context",
                "Expected TTFT",
                "tok/s",
                "State",
              ]}
            >
              {models.map((model) => (
                <tr
                  key={model.id}
                  onClick={() => select(model.slug)}
                  className={`cursor-pointer transition-colors ${
                    model.slug === active?.slug ? "bg-signal/6" : "hover:bg-raised/40"
                  }`}
                >
                  <Td mono>
                    {model.slug}
                    <span className="ml-2 text-[10.5px] text-faint">{model.display_name}</span>
                  </Td>
                  <Td className="text-muted">{model.provider}</Td>
                  <Td>
                    <Pill
                      tone={
                        model.tier >= 4 ? "crit" : model.tier === 3 ? "warn" : model.tier === 2 ? "info" : "ok"
                      }
                    >
                      {model.tier} · {TIER_LABEL[model.tier]}
                    </Pill>
                  </Td>
                  <Td mono>${num(model.input_price_per_mtok, 3)}</Td>
                  <Td mono>${num(model.output_price_per_mtok, 3)}</Td>
                  <Td mono className="text-faint">
                    {int(model.context_window)}
                  </Td>
                  <Td mono>{ms(model.expected_ttft_ms)}</Td>
                  <Td mono>{num(model.expected_tokens_per_second, 0)}</Td>
                  <Td>
                    {model.enabled ? (
                      blocked.get(model.slug) ? (
                        <Pill tone="warn">{blocked.get(model.slug)}</Pill>
                      ) : (
                        <Pill tone="ok" dot>
                          routable
                        </Pill>
                      )
                    ) : (
                      <Pill tone="neutral">disabled</Pill>
                    )}
                  </Td>
                </tr>
              ))}
            </Table>
          )}
        </div>
      </Panel>

      {edited && active ? (
        <div className="grid gap-4 xl:grid-cols-3">
          <Panel className="xl:col-span-2">
            <PanelHeader
              title={`Edit ${active.slug}`}
              hint={active.notes || undefined}
              action={
                <div className="flex items-center gap-2">
                  {dirty ? <Pill tone="warn">unsaved</Pill> : null}
                  <Button
                    size="sm"
                    variant="primary"
                    disabled={!signedIn || !dirty}
                    busy={pending === "save"}
                    onClick={() => void save()}
                  >
                    Save & mark verified
                  </Button>
                </div>
              }
            />
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Input $/Mtok">
                <NumberInput
                  value={edited.input_price_per_mtok ?? 0}
                  onChange={(v) => setDraft({ ...draft, input_price_per_mtok: v })}
                  min={0}
                  step={0.01}
                />
              </Field>
              <Field label="Output $/Mtok">
                <NumberInput
                  value={edited.output_price_per_mtok ?? 0}
                  onChange={(v) => setDraft({ ...draft, output_price_per_mtok: v })}
                  min={0}
                  step={0.01}
                />
              </Field>
              <Field label="Cached input $/Mtok" hint="Prompt-cache hits are billed lower.">
                <NumberInput
                  value={edited.cached_input_price_per_mtok ?? 0}
                  onChange={(v) => setDraft({ ...draft, cached_input_price_per_mtok: v })}
                  min={0}
                  step={0.001}
                />
              </Field>
              <Field label="Capability tier" hint="1 trivial, 4 frontier.">
                <NumberInput
                  value={edited.tier ?? 1}
                  onChange={(v) => setDraft({ ...draft, tier: v })}
                  min={1}
                  max={4}
                />
              </Field>
              <Field label="Max output tokens">
                <NumberInput
                  value={edited.max_output_tokens ?? 1024}
                  onChange={(v) => setDraft({ ...draft, max_output_tokens: v })}
                  min={16}
                  max={32000}
                  step={256}
                />
              </Field>
              <Field label="Expected TTFT (ms)" hint="Drives the latency-first strategy.">
                <NumberInput
                  value={edited.expected_ttft_ms ?? 0}
                  onChange={(v) => setDraft({ ...draft, expected_ttft_ms: v })}
                  min={0}
                  step={10}
                />
              </Field>
              <Field label="Expected tok/s">
                <NumberInput
                  value={edited.expected_tokens_per_second ?? 1}
                  onChange={(v) => setDraft({ ...draft, expected_tokens_per_second: v })}
                  min={1}
                  step={5}
                />
              </Field>
              {active.provider === "simulated" ? (
                <Field
                  label="Simulated failure rate"
                  hint="Inject upstream failures to exercise retries and the breaker."
                >
                  <NumberInput
                    value={edited.simulated_failure_rate ?? 0}
                    onChange={(v) => setDraft({ ...draft, simulated_failure_rate: v })}
                    min={0}
                    max={1}
                    step={0.05}
                  />
                </Field>
              ) : null}
            </div>

            <div className="mt-3 rounded-lg border border-line bg-raised/50 px-3 py-1">
              <Toggle
                checked={edited.enabled ?? false}
                onChange={(v) => setDraft({ ...draft, enabled: v })}
                label="Enabled for routing"
                hint="A disabled row stays in the catalogue but never receives traffic."
              />
            </div>

            {active.provider !== "simulated" ? (
              <Notice tone="info">
                Prices for live upstreams are seeded from the provider&apos;s published rates and may
                be stale. Confirm against{" "}
                {active.price_source ? (
                  <a
                    href={active.price_source}
                    target="_blank"
                    rel="noreferrer"
                    className="underline"
                  >
                    the pricing page
                  </a>
                ) : (
                  "the provider's pricing page"
                )}{" "}
                and save to stamp a verification date.
              </Notice>
            ) : null}
          </Panel>

          <Panel>
            <PanelHeader
              title="Row detail"
              action={
                signedIn ? (
                  <Button
                    size="sm"
                    variant={active.enabled ? "danger" : "secondary"}
                    busy={pending === `toggle-${active.slug}`}
                    onClick={() => void toggle(active)}
                  >
                    {active.enabled ? "Disable" : "Enable"}
                  </Button>
                ) : undefined
              }
            />
            <KeyValue
              rows={[
                ["Slug", active.slug],
                ["Upstream id", active.upstream_model],
                ["Provider", active.provider],
                ["Tier", `${active.tier} · ${TIER_LABEL[active.tier]}`],
                ["Context window", int(active.context_window)],
                ["Capabilities", active.capabilities.join(", ") || "—"],
                [
                  "Price verified",
                  active.price_verified_at ? stamp(active.price_verified_at) : "never",
                ],
                ["Added", ago(active.created_at)],
              ]}
            />
            {active.notes ? (
              <p className="mt-3 rounded-lg border border-line bg-raised/50 p-2.5 text-[11.5px] leading-relaxed text-muted">
                {active.notes}
              </p>
            ) : null}
          </Panel>
        </div>
      ) : (
        <Empty title="No catalogue rows" />
      )}
    </div>
  );
}
