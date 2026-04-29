import { NextRequest, NextResponse } from "next/server";
import { BACKEND_URL, COOKIE_NAME } from "@/lib/server-api";

export async function POST(req: NextRequest) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON body" }, { status: 400 });
  }

  const r = await fetch(`${BACKEND_URL}/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });

  const text = await r.text();
  const parsed = text ? safeParse(text) : null;

  if (!r.ok) {
    return NextResponse.json(parsed ?? { detail: "Login failed" }, { status: r.status });
  }

  const token = (parsed as { access_token?: string } | null)?.access_token;
  if (!token) {
    return NextResponse.json({ detail: "Backend returned no access_token" }, { status: 502 });
  }

  const maxAge = Number(process.env.JWT_COOKIE_MAX_AGE_S ?? "86400");
  const res = NextResponse.json({ ok: true });
  res.cookies.set({
    name: COOKIE_NAME,
    value: token,
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge,
  });
  return res;
}

function safeParse(s: string): unknown {
  try {
    return JSON.parse(s);
  } catch {
    return s;
  }
}
