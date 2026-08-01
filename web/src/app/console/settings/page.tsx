"use client";

import Link from "next/link";
import { useState } from "react";
import {
  Bar,
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
  Skeleton,
  StatusPill,
  Table,
  Td,
  TextInput,
  Toggle,
} from "@/components/ui";
import { api } from "@/lib/api";
import { ago, duration, int, ms, num, pct, stamp } from "@/lib/format";
import { useAction, usePoll, useSession } from "@/lib/hooks";
import type { ApiKey, CacheStats, RuntimeConfig, SystemInfo } from "@/lib/types";

type AuditEntry = {
  id: string;
  actor: string;
  action: string;
  target: string;
  meta: Record<string, unknown>;
  created_at: string;
};

type KeyUsage = {
  keys: {
    id: string;
    name: string;
    prefix: string;
    policy: string;
    requests: number;
    tokens: number;
    spent_usd: number;
    budget_usd: number;
    budget_used: number;
    rpm_limit: number;
    tpm_limit: number;
    revoked: boolean;
    last_used_at: string | null;
  }[];
};

export default function SettingsPage() {
  const { signedIn } = useSession();
  const { data: server, refresh: refreshRuntime } = usePoll<RuntimeConfig>("/api/runtime", 20000);
  const { data: system } = usePoll<SystemInfo>("/api/system", 10000);
  const { data: cache, refresh: refreshCache } = usePoll<CacheStats>("/api/cache", 15000);
  const { data: usage, refresh: refreshUsage } = usePoll<KeyUsage>("/api/analytics/keys", 20000);
  const { data: keys, refresh: refreshKeys } = usePoll<ApiKey[]>(
    signedIn ? "/api/auth/keys" : null,
    0,
  );
  const { data: audit } = usePoll<AuditEntry[]>("/api/audit?limit=40", 20000);
  const { run, pending, error, notice, setError, setNotice } = useAction();

  const [edits, setEdits] = useState<Partial<RuntimeConfig>>({});
  const [keyName, setKeyName] = useState("service-client");
  const [keyBudget, setKeyBudget] = useState(25);
  const [minted, setMinted] = useState<string | null>(null);

  const draft = server ? { ...server, ...edits } : null;
  const dirty = Object.keys(edits).length > 0;

  const save = async () => {
    if (!draft) return;
    await run("save", () => api("/api/runtime", { method: "PUT", body: draft }), "Policy saved");
    setEdits({});
    refreshRuntime();
  };

  const createKey = async () => {
    const created = await run(
      "key",
      () =>
        api<ApiKey>("/api/auth/keys", {
          method: "POST",
          body: { name: keyName, monthly_budget_usd: keyBudget },
        }),
      "Key created — copy it now, it is shown once",
    );
    if (created?.token) setMinted(created.token);
    refreshKeys();
    refreshUsage();
  };

  if (!draft || !system) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-72" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <SectionTitle hint="Runtime policy the hot path reads on every request: caching, tracing, retries, breaker thresholds and the objectives the dashboard grades against. Changes take effect on the next call, not the next deploy.">
        Settings
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
      {!signedIn ? (
        <Notice tone="info">
          Read-only view.{" "}
          <Link href="/login" className="underline">
            Sign in
          </Link>{" "}
          to change policy or mint keys.
        </Notice>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-3">
        <Panel className="xl:col-span-2">
          <PanelHeader
            title="Runtime policy"
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
                  Save
                </Button>
              </div>
            }
          />
          <div className="grid gap-x-6 md:grid-cols-2">
            <div className="divide-y divide-line">
              <Toggle
                checked={draft.cache_enabled}
                onChange={(v) => setEdits({ ...edits, cache_enabled: v })}
                label="Response cache"
                hint="Exact-match on a canonical hash of messages and parameters."
              />
              <Toggle
                checked={draft.tracing_enabled}
                onChange={(v) => setEdits({ ...edits, tracing_enabled: v })}
                label="Span recording"
                hint="Turning this off is how the load test measures its cost."
              />
              <Toggle
                checked={draft.redact_pii}
                onChange={(v) => setEdits({ ...edits, redact_pii: v })}
                label="Redact PII and credentials"
                hint="Emails, phone numbers, card-like digits and API-key patterns."
              />
            </div>
            <div className="space-y-3 pt-3 md:pt-0">
              <Field label="Cache TTL (seconds)">
                <NumberInput
                  value={draft.cache_ttl_seconds}
                  onChange={(v) => setEdits({ ...edits, cache_ttl_seconds: v })}
                  min={10}
                  max={604800}
                  step={60}
                />
              </Field>
              <Field
                label="Cacheable temperature ceiling"
                hint="Above this, only an explicit cache:true is honoured."
              >
                <NumberInput
                  value={draft.cache_max_temperature}
                  onChange={(v) => setEdits({ ...edits, cache_max_temperature: v })}
                  min={0}
                  max={2}
                  step={0.05}
                />
              </Field>
            </div>
          </div>

          <div className="mt-4 grid gap-3 border-t border-line pt-4 md:grid-cols-2 xl:grid-cols-3">
            <Field label="Max upstream attempts">
              <NumberInput
                value={draft.max_attempts}
                onChange={(v) => setEdits({ ...edits, max_attempts: v })}
                min={1}
                max={6}
              />
            </Field>
            <Field label="Breaker failure threshold">
              <NumberInput
                value={draft.circuit_failure_threshold}
                onChange={(v) => setEdits({ ...edits, circuit_failure_threshold: v })}
                min={1}
                max={100}
              />
            </Field>
            <Field label="Breaker reset (seconds)">
              <NumberInput
                value={draft.circuit_reset_seconds}
                onChange={(v) => setEdits({ ...edits, circuit_reset_seconds: v })}
                min={1}
                max={3600}
                step={5}
              />
            </Field>
            <Field label="Default RPM limit">
              <NumberInput
                value={draft.default_rpm_limit}
                onChange={(v) => setEdits({ ...edits, default_rpm_limit: v })}
                min={1}
                max={100000}
                step={10}
              />
            </Field>
            <Field label="Default TPM limit">
              <NumberInput
                value={draft.default_tpm_limit}
                onChange={(v) => setEdits({ ...edits, default_tpm_limit: v })}
                min={100}
                max={50000000}
                step={1000}
              />
            </Field>
            <Field label="TTFT objective (ms)">
              <NumberInput
                value={draft.slo_ttft_ms}
                onChange={(v) => setEdits({ ...edits, slo_ttft_ms: v })}
                min={50}
                max={60000}
                step={50}
              />
            </Field>
            <Field label="Availability objective">
              <NumberInput
                value={draft.slo_availability}
                onChange={(v) => setEdits({ ...edits, slo_availability: v })}
                min={0.5}
                max={1}
                step={0.001}
              />
            </Field>
          </div>

          <p className="mt-3 text-[11px] leading-relaxed text-faint">
            Rate limits are token buckets held per process. With N replicas the effective ceiling is
            N times these values — a shared counter in Redis is the fix, and this is stated rather
            than hidden.
          </p>
        </Panel>

        <div className="space-y-4">
          <Panel>
            <PanelHeader title="Runtime" />
            <KeyValue
              rows={[
                ["Version", `${system.app.version} (${system.app.git_sha})`],
                ["Environment", system.app.env],
                ["Region", system.app.region],
                ["Uptime", duration(system.app.uptime_seconds * 1000)],
                ["Database", system.infrastructure.database],
                [
                  "Upstreams",
                  system.infrastructure.providers_configured.join(", ") || "none",
                ],
                [
                  "Live upstreams",
                  system.infrastructure.live_providers.join(", ") || "simulated only",
                ],
                ["OTLP endpoint", system.infrastructure.otlp_endpoint ?? "local spans only"],
                ["Buffered spans", int(system.tracing.buffered_spans)],
                ["Dropped spans", int(system.tracing.dropped_spans)],
                ["Span retention", `${system.tracing.retention_hours}h`],
                [
                  "Concurrency",
                  `${system.concurrency.inflight}/${system.concurrency.max_concurrency} (peak ${system.concurrency.peak_inflight})`,
                ],
                ["Upstream timeout", `${system.limits.upstream_timeout_seconds}s`],
                ["Max prompt", `${int(system.limits.max_prompt_chars)} chars`],
                ["Output cap", `${int(system.limits.max_output_tokens_cap)} tokens`],
              ]}
            />
          </Panel>

          <Panel>
            <PanelHeader
              title="Response cache"
              action={
                signedIn ? (
                  <Button
                    size="sm"
                    variant="danger"
                    busy={pending === "purge"}
                    onClick={() =>
                      void run(
                        "purge",
                        () => api("/api/cache", { method: "DELETE" }),
                        "Cache purged",
                      ).then(refreshCache)
                    }
                  >
                    Purge
                  </Button>
                ) : undefined
              }
            />
            {cache ? (
              <KeyValue
                rows={[
                  ["Enabled", cache.enabled ? "yes" : "no"],
                  ["Entries", `${int(cache.entries)} / ${int(cache.max_entries)}`],
                  ["Hits", int(cache.hits)],
                  ["Spend avoided", `$${num(cache.saved_usd, 6)}`],
                  ["Cached output tokens", int(cache.cached_completion_tokens)],
                  ["TTL", `${cache.ttl_seconds}s`],
                ]}
              />
            ) : (
              <Skeleton className="h-32" />
            )}
          </Panel>

          <Panel>
            <PanelHeader title="Circuit breakers" hint="Per provider, per replica." />
            {system.providers.length ? (
              <div className="space-y-2">
                {system.providers.map((provider) => (
                  <div
                    key={provider.provider}
                    className="flex items-center justify-between gap-2 rounded-lg border border-line bg-raised/50 px-2.5 py-2"
                  >
                    <div className="min-w-0">
                      <p className="num text-[12.5px] text-ink">{provider.provider}</p>
                      <p className="num text-[10.5px] text-faint">
                        {int(provider.total_requests)} calls · {pct(provider.failure_ratio, 1)} fail
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <StatusPill
                        status={provider.state === "closed" ? "live" : provider.state}
                      />
                      {signedIn && provider.state !== "closed" ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          busy={pending === `reset-${provider.provider}`}
                          onClick={() =>
                            void run(`reset-${provider.provider}`, () =>
                              api(`/api/providers/${provider.provider}/reset`, { method: "POST" }),
                            )
                          }
                        >
                          reset
                        </Button>
                      ) : null}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <Empty title="No upstream calls yet" />
            )}
          </Panel>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel>
          <PanelHeader
            title="Data-plane keys"
            hint="PBKDF2-hashed, prefix-indexed, with their own rate limits and monthly budget."
          />
          {signedIn ? (
            <>
              <div className="flex items-end gap-2">
                <Field label="Key name" className="flex-1">
                  <TextInput value={keyName} onChange={setKeyName} mono />
                </Field>
                <Field label="Budget $/mo">
                  <NumberInput value={keyBudget} onChange={setKeyBudget} min={0} max={100000} />
                </Field>
                <Button busy={pending === "key"} onClick={() => void createKey()}>
                  Create
                </Button>
              </div>
              {minted ? (
                <div className="mt-3">
                  <Notice tone="warn" onDismiss={() => setMinted(null)}>
                    <span className="num break-all">{minted}</span>
                  </Notice>
                </div>
              ) : null}
              <div className="mt-3">
                {keys?.length ? (
                  <Table head={["Name", "Prefix", "Spend", "Requests", "Last used", ""]}>
                    {keys.map((key) => (
                      <tr key={key.id} className={key.revoked ? "opacity-50" : undefined}>
                        <Td>{key.name}</Td>
                        <Td mono className="text-muted">
                          {key.prefix}…
                        </Td>
                        <Td mono>
                          ${num(key.spent_usd, 4)}
                          <span className="text-faint"> / {num(key.monthly_budget_usd, 0)}</span>
                        </Td>
                        <Td mono>{int(key.request_count)}</Td>
                        <Td className="text-faint">
                          {key.last_used_at ? ago(key.last_used_at) : "never"}
                        </Td>
                        <Td>
                          {key.revoked ? (
                            <Pill tone="neutral">revoked</Pill>
                          ) : (
                            <Button
                              size="sm"
                              variant="ghost"
                              busy={pending === `revoke-${key.id}`}
                              onClick={() =>
                                void run(`revoke-${key.id}`, () =>
                                  api(`/api/auth/keys/${key.id}`, { method: "DELETE" }),
                                ).then(refreshKeys)
                              }
                            >
                              revoke
                            </Button>
                          )}
                        </Td>
                      </tr>
                    ))}
                  </Table>
                ) : (
                  <Empty title="No keys yet" />
                )}
              </div>
            </>
          ) : (
            <Empty title="Sign in to manage keys" />
          )}
          <p className="mt-3 text-[11px] text-faint">
            Send it as <Code>authorization: Bearer sk-sent-…</Code> or <Code>x-api-key</Code>.
          </p>
        </Panel>

        <Panel>
          <PanelHeader title="Budget consumption" hint="Attributed per key at request time." />
          {usage?.keys.length ? (
            <div className="space-y-3">
              {usage.keys.map((key) => (
                <div key={key.id}>
                  <div className="flex items-baseline justify-between text-[12px]">
                    <span className="num text-muted">
                      {key.name}
                      {key.revoked ? " (revoked)" : ""}
                    </span>
                    <span className="num text-ink">
                      ${num(key.spent_usd, 4)} / ${num(key.budget_usd, 2)}
                    </span>
                  </div>
                  <Bar
                    value={Math.min(1, key.budget_used)}
                    tone={key.budget_used > 0.9 ? "crit" : key.budget_used > 0.6 ? "warn" : "ok"}
                    className="mt-1.5"
                  />
                  <p className="num mt-1 text-[10.5px] text-faint">
                    {int(key.requests)} requests · {int(key.tokens)} tokens · {key.rpm_limit} rpm /{" "}
                    {int(key.tpm_limit)} tpm
                  </p>
                </div>
              ))}
            </div>
          ) : (
            <Empty title="No usage attributed yet" />
          )}
        </Panel>
      </div>

      <Panel padded={false}>
        <div className="border-b border-line px-5 py-3">
          <h2 className="text-[13px] font-semibold tracking-tight">Audit log</h2>
        </div>
        <div className="max-h-[380px] overflow-y-auto px-5 py-3">
          {audit?.length ? (
            <Table head={["When", "Actor", "Action", "Target"]}>
              {audit.map((entry) => (
                <tr key={entry.id}>
                  <Td className="text-faint">{stamp(entry.created_at)}</Td>
                  <Td className="text-muted">{entry.actor}</Td>
                  <Td mono>{entry.action}</Td>
                  <Td mono className="max-w-[240px] truncate text-faint">
                    {entry.target || "—"}
                  </Td>
                </tr>
              ))}
            </Table>
          ) : (
            <Empty title="No audit events" />
          )}
        </div>
      </Panel>

      <p className="text-[11px] text-faint">
        Objectives are graded over the dashboard window; TTFT target {ms(draft.slo_ttft_ms)},
        availability {pct(draft.slo_availability, 2)}.
      </p>
    </div>
  );
}
