"use client";

import clsx from "clsx";
import type { ReactNode } from "react";

/* ---------------------------------------------------------------- surfaces */
export function Panel({
  children,
  className,
  padded = true,
}: {
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <section className={clsx("panel", padded && "p-5", className)}>{children}</section>
  );
}

export function PanelHeader({
  title,
  hint,
  action,
  className,
}: {
  title: string;
  hint?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <header className={clsx("mb-4 flex items-start justify-between gap-4", className)}>
      <div className="min-w-0">
        <h2 className="text-[13px] font-semibold tracking-tight text-ink">{title}</h2>
        {hint ? <p className="mt-1 text-xs leading-relaxed text-faint">{hint}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </header>
  );
}

export function SectionTitle({ children, hint }: { children: ReactNode; hint?: string }) {
  return (
    <div className="mb-4">
      <h1 className="text-xl font-semibold tracking-tight text-ink">{children}</h1>
      {hint ? <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-muted">{hint}</p> : null}
    </div>
  );
}

/* ------------------------------------------------------------------ status */
const TONES = {
  neutral: "border-line-strong bg-raised text-muted",
  signal: "border-signal/35 bg-signal/10 text-signal",
  ok: "border-ok/35 bg-ok/10 text-ok",
  warn: "border-warn/35 bg-warn/10 text-warn",
  crit: "border-crit/35 bg-crit/10 text-crit",
  info: "border-info/35 bg-info/10 text-info",
  violet: "border-violet/35 bg-violet/10 text-violet",
} as const;

export type Tone = keyof typeof TONES;

export function Pill({
  children,
  tone = "neutral",
  dot = false,
  className,
}: {
  children: ReactNode;
  tone?: Tone;
  dot?: boolean;
  className?: string;
}) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium",
        TONES[tone],
        className,
      )}
    >
      {dot ? <i className="size-1.5 rounded-full bg-current" /> : null}
      {children}
    </span>
  );
}

export function toneForStatus(status: string): Tone {
  switch (status) {
    case "succeeded":
    case "production":
    case "stable":
    case "live":
    case "pass":
      return "ok";
    case "running":
    case "queued":
    case "pending":
    case "staging":
      return "info";
    case "warning":
    case "canary":
    case "watch":
      return "warn";
    case "failed":
    case "drifted":
    case "critical":
    case "rejected":
    case "rolled_back":
      return "crit";
    case "skipped":
    case "archived":
    case "cancelled":
      return "neutral";
    default:
      return "neutral";
  }
}

export function StatusPill({ status, className }: { status: string; className?: string }) {
  const tone = toneForStatus(status);
  const live = status === "running" || status === "queued";
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize",
        TONES[tone],
        className,
      )}
    >
      <i className={clsx("size-1.5 rounded-full bg-current", live && "pulse-dot")} />
      {status.replace(/_/g, " ")}
    </span>
  );
}

/* ------------------------------------------------------------------ inputs */
const BUTTON_VARIANTS = {
  primary:
    "bg-signal text-[#04161b] hover:bg-signal/90 border-transparent font-semibold shadow-[0_0_0_1px_rgba(34,211,238,0.35)]",
  secondary: "bg-raised text-ink hover:bg-overlay border-line-strong",
  ghost: "bg-transparent text-muted hover:text-ink hover:bg-raised border-transparent",
  danger: "bg-crit/12 text-crit hover:bg-crit/20 border-crit/35",
} as const;

export function Button({
  children,
  onClick,
  variant = "secondary",
  size = "md",
  disabled,
  busy,
  type = "button",
  className,
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: keyof typeof BUTTON_VARIANTS;
  size?: "sm" | "md";
  disabled?: boolean;
  busy?: boolean;
  type?: "button" | "submit";
  className?: string;
  title?: string;
}) {
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled || busy}
      className={clsx(
        "relative inline-flex items-center justify-center gap-2 overflow-hidden rounded-lg border transition-colors",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal/70",
        "disabled:cursor-not-allowed disabled:opacity-45",
        size === "sm" ? "px-2.5 py-1.5 text-xs" : "px-3.5 py-2 text-[13px]",
        BUTTON_VARIANTS[variant],
        className,
      )}
    >
      {busy ? <span className="sweep absolute inset-0 opacity-70" aria-hidden /> : null}
      <span className="relative flex items-center gap-2">{children}</span>
    </button>
  );
}

export function Field({
  label,
  hint,
  children,
  className,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={clsx("block", className)}>
      <span className="label-xs mb-1.5 block">{label}</span>
      {children}
      {hint ? <span className="mt-1 block text-[11px] text-faint">{hint}</span> : null}
    </label>
  );
}

const CONTROL =
  "w-full rounded-lg border border-line-strong bg-raised px-3 py-2 text-[13px] text-ink placeholder:text-faint focus:border-signal/60 focus:outline-none";

export function TextInput({
  value,
  onChange,
  placeholder,
  type = "text",
  mono,
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
  mono?: boolean;
  className?: string;
}) {
  return (
    <input
      type={type}
      value={value}
      placeholder={placeholder}
      onChange={(event) => onChange(event.target.value)}
      className={clsx(CONTROL, mono && "num", className)}
    />
  );
}

export function NumberInput({
  value,
  onChange,
  min,
  max,
  step = 1,
  className,
}: {
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  className?: string;
}) {
  return (
    <input
      type="number"
      value={value}
      min={min}
      max={max}
      step={step}
      onChange={(event) => onChange(Number(event.target.value))}
      className={clsx(CONTROL, "num", className)}
    />
  );
}

export function Select<T extends string>({
  value,
  onChange,
  options,
  className,
}: {
  value: T;
  onChange: (value: T) => void;
  options: { value: T; label: string }[];
  className?: string;
}) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value as T)}
      className={clsx(CONTROL, "appearance-none pr-8", className)}
      style={{
        backgroundImage:
          "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%238c94a7' d='M6 8.5 2 4h8z'/%3E%3C/svg%3E\")",
        backgroundRepeat: "no-repeat",
        backgroundPosition: "right 10px center",
      }}
    >
      {options.map((option) => (
        <option key={option.value} value={option.value} className="bg-panel">
          {option.label}
        </option>
      ))}
    </select>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  hint,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  hint?: string;
}) {
  return (
    <div className="flex items-start justify-between gap-4 py-2.5">
      <div className="min-w-0">
        <p className="text-[13px] text-ink">{label}</p>
        {hint ? <p className="mt-0.5 text-[11px] leading-relaxed text-faint">{hint}</p> : null}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={clsx(
          "relative mt-0.5 h-5 w-9 shrink-0 rounded-full border transition-colors",
          checked ? "border-signal/50 bg-signal/30" : "border-line-strong bg-raised",
        )}
      >
        <span
          className={clsx(
            "absolute top-0.5 size-3.5 rounded-full transition-all",
            checked ? "left-4.5 bg-signal" : "left-0.5 bg-faint",
          )}
        />
      </button>
    </div>
  );
}

/* -------------------------------------------------------------------- data */
export function Stat({
  label,
  value,
  sub,
  tone = "neutral",
  chart,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: Tone;
  chart?: ReactNode;
}) {
  const accent = {
    neutral: "text-ink",
    signal: "text-signal",
    ok: "text-ok",
    warn: "text-warn",
    crit: "text-crit",
    info: "text-info",
    violet: "text-violet",
  }[tone];
  return (
    <div className="panel relative overflow-hidden p-4">
      <p className="label-xs">{label}</p>
      <p className={clsx("num mt-2 text-2xl font-semibold tracking-tight", accent)}>{value}</p>
      {sub ? <p className="mt-1 text-[11px] text-faint">{sub}</p> : null}
      {chart ? <div className="mt-3 h-9">{chart}</div> : null}
    </div>
  );
}

export function KeyValue({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="divide-y divide-line text-[13px]">
      {rows.map(([key, value]) => (
        <div key={key} className="flex items-baseline justify-between gap-4 py-2">
          <dt className="text-muted">{key}</dt>
          <dd className="num max-w-[62%] truncate text-right text-ink">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Table({
  head,
  children,
  className,
}: {
  head: ReactNode[];
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={clsx("overflow-x-auto", className)}>
      <table className="w-full min-w-full border-collapse text-left text-[13px]">
        <thead>
          <tr className="border-b border-line">
            {head.map((cell, index) => (
              <th
                key={index}
                className="label-xs whitespace-nowrap px-3 py-2 first:pl-0 last:pr-0 last:text-right"
              >
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line/70">{children}</tbody>
      </table>
    </div>
  );
}

export function Td({
  children,
  className,
  mono,
}: {
  children: ReactNode;
  className?: string;
  mono?: boolean;
}) {
  return (
    <td
      className={clsx(
        "whitespace-nowrap px-3 py-2.5 align-middle first:pl-0 last:pr-0 last:text-right",
        mono && "num",
        className,
      )}
    >
      {children}
    </td>
  );
}

export function Bar({
  value,
  tone = "signal",
  className,
}: {
  value: number;
  tone?: "signal" | "ok" | "warn" | "crit" | "info";
  className?: string;
}) {
  const colors = {
    signal: "bg-signal",
    ok: "bg-ok",
    warn: "bg-warn",
    crit: "bg-crit",
    info: "bg-info",
  };
  return (
    <div className={clsx("h-1.5 w-full overflow-hidden rounded-full bg-line", className)}>
      <div
        className={clsx("h-full rounded-full transition-[width] duration-500", colors[tone])}
        style={{ width: `${Math.max(1.5, Math.min(100, value * 100))}%` }}
      />
    </div>
  );
}

/* ------------------------------------------------------------------- state */
export function Empty({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-line-strong px-6 py-12 text-center">
      <p className="text-[13px] font-medium text-ink">{title}</p>
      {hint ? <p className="max-w-md text-xs leading-relaxed text-faint">{hint}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded-md bg-raised", className)} />;
}

export function Notice({
  tone,
  children,
  onDismiss,
}: {
  tone: "crit" | "ok" | "warn" | "info";
  children: ReactNode;
  onDismiss?: () => void;
}) {
  return (
    <div
      className={clsx(
        "flex items-start justify-between gap-3 rounded-lg border px-3 py-2 text-xs",
        TONES[tone],
      )}
      role="status"
    >
      <span className="leading-relaxed">{children}</span>
      {onDismiss ? (
        <button
          type="button"
          onClick={onDismiss}
          className="shrink-0 opacity-60 transition-opacity hover:opacity-100"
          aria-label="Dismiss"
        >
          ✕
        </button>
      ) : null}
    </div>
  );
}

export function Code({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <code
      className={clsx(
        "num rounded-md border border-line bg-raised px-1.5 py-0.5 text-[11.5px] text-muted",
        className,
      )}
    >
      {children}
    </code>
  );
}
