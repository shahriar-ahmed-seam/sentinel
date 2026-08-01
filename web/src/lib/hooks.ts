"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, getSubject, url } from "./api";
import type { LiveEvent } from "./types";

/** Polling fetcher with abort handling and a stable manual refresh. */
export function usePoll<T>(path: string | null, intervalMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      if (!path) return;
      try {
        const result = await api<T>(path, { signal });
        if (!mounted.current) return;
        setData(result);
        setError(null);
      } catch (err) {
        if (!mounted.current) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(err instanceof ApiError ? err.message : "Network error");
      }
    },
    [path],
  );

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    // Deferred to a microtask so the first fetch cannot resolve during the
    // effect's commit phase and trigger a cascading render.
    queueMicrotask(() => void load(controller.signal));
    let timer: ReturnType<typeof setInterval> | undefined;
    if (intervalMs > 0) {
      timer = setInterval(() => load(), intervalMs);
    }
    return () => {
      mounted.current = false;
      controller.abort();
      if (timer) clearInterval(timer);
    };
  }, [load, intervalMs]);

  // Derived rather than stored: nothing has arrived and nothing has failed.
  const loading = Boolean(path) && data === null && error === null;

  return { data, error, loading, refresh: () => void load() };
}

/** Server-sent events from the control plane, with auto-reconnect. */
export function useEventStream(limit = 60) {
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let source: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let closed = false;

    const connect = () => {
      source = new EventSource(url("/api/stream"));
      source.onopen = () => setConnected(true);
      source.onmessage = () => undefined;
      source.onerror = () => {
        setConnected(false);
        source?.close();
        if (!closed) retry = setTimeout(connect, 4000);
      };
      const handler = (event: MessageEvent) => {
        try {
          const parsed = JSON.parse(event.data) as LiveEvent;
          setEvents((current) => [parsed, ...current].slice(0, limit));
        } catch {
          /* ignore malformed frames */
        }
      };
      for (const kind of [
        "hello",
        "request.completed",
        "request.failed",
        "cache.hit",
        "route.decision",
        "circuit.changed",
        "loadtest.stage",
        "loadtest.finished",
        "budget.warning",
        "alert",
        "audit",
        "catalog.changed",
        "policy.changed",
      ]) {
        source.addEventListener(kind, handler as EventListener);
      }
    };

    connect();
    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      source?.close();
    };
  }, [limit]);

  return { events, connected };
}

/** Tracks operator session state across tabs. */
export function useSession() {
  const [subject, setSubject] = useState<string | null>(null);

  useEffect(() => {
    const sync = () => setSubject(getSubject());
    sync();
    window.addEventListener("sentinel:session", sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener("sentinel:session", sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  return { subject, signedIn: Boolean(subject) };
}

/** Mutation helper that surfaces pending/error state to buttons. */
export function useAction() {
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const run = useCallback(
    async <T,>(key: string, fn: () => Promise<T>, successMessage?: string): Promise<T | null> => {
      setPending(key);
      setError(null);
      setNotice(null);
      try {
        const result = await fn();
        if (successMessage) setNotice(successMessage);
        return result;
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Request failed");
        return null;
      } finally {
        setPending(null);
      }
    },
    [],
  );

  return { run, pending, error, notice, setError, setNotice };
}
