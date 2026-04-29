import { NextRequest, NextResponse } from "next/server";
import { BackendError, backendJson } from "@/lib/server-api";
import type { Session } from "@/lib/types";

export async function POST(req: NextRequest) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON body" }, { status: 400 });
  }

  try {
    const session = await backendJson<Session>("/sessions/", {
      method: "POST",
      body: JSON.stringify(body),
    });
    return NextResponse.json(session);
  } catch (e) {
    if (e instanceof BackendError) {
      return NextResponse.json(e.body ?? { detail: "Backend error" }, { status: e.status });
    }
    return NextResponse.json({ detail: String(e) }, { status: 502 });
  }
}
