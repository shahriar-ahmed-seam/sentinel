"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Mark } from "@/components/shell";
import { Button, Field, Notice, TextInput } from "@/components/ui";
import { ApiError, login } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("admin@sentinel.dev");
  const [password, setPassword] = useState("sentinel");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      router.push("/console");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the gateway");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="grid min-h-dvh place-items-center px-4">
      <div className="grid-bg pointer-events-none fixed inset-0 opacity-60" aria-hidden />
      <div className="relative w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2.5">
          <Mark />
          <div>
            <p className="text-[15px] font-semibold tracking-tight">Sentinel</p>
            <p className="text-[11px] text-faint">operator sign-in</p>
          </div>
        </div>

        <form
          className="panel space-y-4 p-5"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <Field label="Operator email">
            <TextInput value={email} onChange={setEmail} type="email" />
          </Field>
          <Field label="Password">
            <TextInput value={password} onChange={setPassword} type="password" />
          </Field>
          {error ? <Notice tone="crit">{error}</Notice> : null}
          <Button type="submit" variant="primary" busy={busy} className="w-full">
            Sign in
          </Button>
          <p className="text-[11px] leading-relaxed text-faint">
            Dashboards are public on this demo. Changing policy, editing the price book, minting
            keys and launching load tests need the operator token. Credentials come from{" "}
            <code className="num text-muted">ADMIN_EMAIL</code> /{" "}
            <code className="num text-muted">ADMIN_PASSWORD</code> and must be changed before this is
            reachable from the internet.
          </p>
        </form>

        <div className="mt-5 flex items-center justify-between text-[11px] text-faint">
          <Link href="/" className="transition-colors hover:text-muted">
            ← back
          </Link>
          <Link href="/console" className="transition-colors hover:text-muted">
            browse read-only →
          </Link>
        </div>
      </div>
    </main>
  );
}
