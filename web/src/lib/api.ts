"use client";

export const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");
const TOKEN_KEY = "sentinel.token";
const SUBJECT_KEY = "sentinel.subject";

export function url(path: string): string {
  return `${API_BASE}${path}`;
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function getSubject(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(SUBJECT_KEY);
}

export function setSession(token: string, subject: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(SUBJECT_KEY, subject);
  window.dispatchEvent(new Event("sentinel:session"));
}

export function clearSession(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(SUBJECT_KEY);
  window.dispatchEvent(new Event("sentinel:session"));
}

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

type Options = {
  method?: string;
  body?: unknown;
  auth?: boolean;
  signal?: AbortSignal;
};

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const { method = "GET", body, auth = true, signal } = options;
  const headers: Record<string, string> = { accept: "application/json" };
  if (body !== undefined) headers["content-type"] = "application/json";
  const token = auth ? getToken() : null;
  if (token) headers.authorization = `Bearer ${token}`;

  const response = await fetch(url(path), {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
    cache: "no-store",
  });

  if (response.status === 401) {
    if (token) clearSession();
    throw new ApiError(401, "Sign in required");
  }

  const text = await response.text();
  const payload = text ? safeParse(text) : null;

  if (!response.ok) {
    const detail = (payload as { detail?: unknown })?.detail;
    throw new ApiError(
      response.status,
      typeof detail === "string" ? detail : `Request failed (${response.status})`,
      detail,
    );
  }
  return payload as T;
}

function safeParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export async function login(email: string, password: string): Promise<string> {
  const data = await api<{ access_token: string; subject: string }>("/api/auth/login", {
    method: "POST",
    body: { email, password },
    auth: false,
  });
  setSession(data.access_token, data.subject);
  return data.subject;
}
