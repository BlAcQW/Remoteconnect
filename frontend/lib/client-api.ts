import type { Machine, Session } from "./types";

export class ApiError extends Error {
  constructor(public status: number, public body: unknown) {
    super(typeof body === "object" && body && "detail" in body ? String((body as { detail: unknown }).detail) : `Request failed (${status})`);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(path, {
    ...init,
    credentials: "include",
    headers: {
      accept: "application/json",
      ...(init.body ? { "content-type": "application/json" } : {}),
      ...(init.headers ?? {}),
    },
  });
  const text = await r.text();
  const body = text ? safeParse(text) : null;
  if (!r.ok) throw new ApiError(r.status, body);
  return body as T;
}

function safeParse(s: string): unknown {
  try {
    return JSON.parse(s);
  } catch {
    return s;
  }
}

export const api = {
  login: (email: string, password: string) =>
    request<{ ok: true }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  logout: () => request<{ ok: true }>("/api/auth/logout", { method: "POST" }),
  machines: () => request<Machine[]>("/api/machines"),
  deleteMachine: (id: string) =>
    request<{ status: string }>(`/api/machines/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  createSession: (machine_id: string) =>
    request<Session>("/api/sessions", {
      method: "POST",
      body: JSON.stringify({ machine_id }),
    }),
  endSession: (id: string) =>
    request<{ status: string }>(`/api/sessions/${encodeURIComponent(id)}/end`, {
      method: "POST",
    }),
};
