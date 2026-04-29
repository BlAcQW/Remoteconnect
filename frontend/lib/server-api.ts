/**
 * Thin server-side wrapper around the FastAPI backend. Reads the JWT from
 * the httpOnly cookie set during login and attaches it as a Bearer header.
 *
 * Use only inside Route Handlers, server components, or server actions —
 * never imported into client code.
 */
import { cookies } from "next/headers";

export const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8765";
export const COOKIE_NAME = process.env.JWT_COOKIE_NAME ?? "rc_jwt";

export class BackendError extends Error {
  constructor(public status: number, public body: unknown) {
    super(`Backend ${status}`);
  }
}

function authHeader(): Record<string, string> {
  const jwt = cookies().get(COOKIE_NAME)?.value;
  return jwt ? { authorization: `Bearer ${jwt}` } : {};
}

export async function backendFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const url = `${BACKEND_URL}${path}`;
  const headers = new Headers(init.headers);
  headers.set("accept", "application/json");
  for (const [k, v] of Object.entries(authHeader())) headers.set(k, v);
  if (init.body && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }
  return fetch(url, { ...init, headers, cache: "no-store" });
}

export async function backendJson<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const r = await backendFetch(path, init);
  const text = await r.text();
  const body = text ? safeParse(text) : null;
  if (!r.ok) throw new BackendError(r.status, body);
  return body as T;
}

function safeParse(s: string): unknown {
  try {
    return JSON.parse(s);
  } catch {
    return s;
  }
}
