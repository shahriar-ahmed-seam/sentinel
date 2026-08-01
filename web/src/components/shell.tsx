"use client";

import clsx from "clsx";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { clearSession, url } from "@/lib/api";
import { useEventStream, usePoll, useSession } from "@/lib/hooks";
import type { SystemInfo } from "@/lib/types";
import {
  IconBox,
  IconFlow,
  IconGauge,
  IconLayers,
  IconPulse,
  IconSliders,
  IconTerminal,
} from "./icons";
import { Pill } from "./ui";

const NAV = [
  { href: "/console", label: "Overview", Icon: IconGauge },
  { href: "/console/requests", label: "Requests", Icon: IconLayers },
  { href: "/console/traces", label: "Traces", Icon: IconPulse },
  { href: "/console/routing", label: "Routing", Icon: IconFlow },
  { href: "/console/models", label: "Catalogue", Icon: IconBox },
  { href: "/console/playground", label: "Playground", Icon: IconTerminal },
  { href: "/console/load", label: "Load tests", Icon: IconPulse },
  { href: "/console/settings", label: "Settings", Icon: IconSliders },
];

export function Mark({ className }: { className?: string }) {
  return (
    <span className={clsx("relative inline-flex size-7 items-center justify-center", className)}>
      <svg viewBox="0 0 32 32" className="size-7" aria-hidden>
        <path
          d="M16 3 5.5 8v8.6c0 6 4.4 10.7 10.5 12.4 6.1-1.7 10.5-6.4 10.5-12.4V8z"
          fill="none"
          stroke="#22d3ee"
          strokeWidth="1.6"
          opacity="0.55"
        />
        <path d="M10.5 16.4l3.4 3.4 7.6-7.6" fill="none" stroke="#22d3ee" strokeWidth="1.9" />
        <circle cx="16" cy="3" r="1.9" fill="#22d3ee" />
      </svg>
    </span>
  );
}

export function ConsoleShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { connected } = useEventStream(120);
  const { signedIn, subject } = useSession();
  const { data: system } = usePoll<SystemInfo>("/api/system", 15000);
  const [open, setOpen] = useState(false);

  const active = (href: string) =>
    href === "/console" ? pathname === href : pathname.startsWith(href);

  const liveProviders = system?.infrastructure.live_providers ?? [];
  const openCircuits = (system?.providers ?? []).filter((p) => p.state === "open");

  return (
    <div className="flex min-h-dvh">
      <aside
        className={clsx(
          "fixed inset-y-0 left-0 z-40 flex w-60 flex-col border-r border-line bg-panel/80 backdrop-blur transition-transform lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex h-14 items-center gap-2.5 border-b border-line px-4">
          <Link href="/" className="flex items-center gap-2.5">
            <Mark />
            <span className="text-[15px] font-semibold tracking-tight">Sentinel</span>
          </Link>
          <span className="label-xs ml-auto">{system?.app.env ?? "—"}</span>
        </div>

        <nav className="flex-1 space-y-0.5 p-3">
          {NAV.map(({ href, label, Icon }) => (
            <Link
              key={href}
              href={href}
              onClick={() => setOpen(false)}
              className={clsx(
                "group flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] transition-colors",
                active(href)
                  ? "bg-signal/10 text-signal"
                  : "text-muted hover:bg-raised hover:text-ink",
              )}
            >
              <Icon className="size-4 shrink-0" />
              {label}
            </Link>
          ))}
        </nav>

        <div className="space-y-2 border-t border-line p-3">
          <Row label="event stream">
            <span className="flex items-center gap-1.5">
              <i
                className={clsx("size-1.5 rounded-full", connected ? "bg-ok pulse-dot" : "bg-crit")}
              />
              {connected ? "live" : "offline"}
            </span>
          </Row>
          <Row label="in flight">
            <span className="num text-muted">
              {system?.concurrency.inflight ?? "—"}/{system?.concurrency.max_concurrency ?? "—"}
            </span>
          </Row>
          <Row label="upstreams">
            <span className="num text-muted">
              {(system?.infrastructure.providers_configured ?? []).length || "—"}
              {liveProviders.length ? ` · ${liveProviders.length} live` : ""}
            </span>
          </Row>
          {openCircuits.length ? (
            <Row label="circuits">
              <span className="num text-crit">{openCircuits.length} open</span>
            </Row>
          ) : null}

          {signedIn ? (
            <button
              type="button"
              onClick={() => clearSession()}
              className="mt-1 w-full rounded-lg border border-line-strong bg-raised px-2.5 py-1.5 text-left text-[11px] text-muted transition-colors hover:text-ink"
            >
              Sign out
              <span className="block truncate text-[10px] text-faint">{subject}</span>
            </button>
          ) : (
            <Link
              href="/login"
              className="mt-1 block rounded-lg border border-signal/35 bg-signal/10 px-2.5 py-1.5 text-center text-[11px] font-medium text-signal"
            >
              Sign in to operate
            </Link>
          )}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col lg:pl-60">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-base/85 px-4 backdrop-blur lg:px-8">
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            className="rounded-md border border-line-strong p-1.5 text-muted lg:hidden"
            aria-label="Toggle navigation"
          >
            <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor">
              <path d="M4 7h16M4 12h16M4 17h16" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>
          <p className="truncate text-[13px] font-medium text-muted">
            {NAV.find((item) => active(item.href))?.label ?? "Console"}
          </p>
          <div className="ml-auto flex items-center gap-2">
            {system?.infrastructure.simulate_only ? (
              <Pill tone="warn">simulate-only</Pill>
            ) : liveProviders.length ? (
              <Pill tone="ok" dot>
                live: {liveProviders.join(", ")}
              </Pill>
            ) : (
              <Pill tone="neutral" dot>
                simulated upstreams
              </Pill>
            )}
            {system?.loadtest.running ? <Pill tone="info" dot>load test running</Pill> : null}
            {!signedIn ? <Pill tone="neutral">read-only</Pill> : <Pill tone="signal">operator</Pill>}
          </div>
        </header>

        <main className="min-w-0 flex-1 px-4 py-6 lg:px-8">
          <div className="mx-auto max-w-[1360px]">{children}</div>
        </main>

        <footer className="border-t border-line px-4 py-4 text-[11px] text-faint lg:px-8">
          <div className="mx-auto flex max-w-[1360px] flex-wrap items-center gap-x-4 gap-y-1">
            <span>
              Sentinel {system?.app.version ?? ""} · {system?.infrastructure.database ?? "—"} ·{" "}
              {system?.tracing.otlp_mirroring ? "OTLP mirroring on" : "spans local"}
            </span>
            <a
              href={url("/docs")}
              target="_blank"
              rel="noreferrer"
              className="transition-colors hover:text-muted"
            >
              OpenAPI
            </a>
            <a
              href={url("/metrics")}
              target="_blank"
              rel="noreferrer"
              className="transition-colors hover:text-muted"
            >
              Prometheus
            </a>
          </div>
        </footer>
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between text-[11px] text-faint">
      <span>{label}</span>
      {children}
    </div>
  );
}
