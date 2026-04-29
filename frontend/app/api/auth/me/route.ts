import { NextResponse } from "next/server";
import { BackendError, backendJson } from "@/lib/server-api";

export async function GET() {
  try {
    const me = await backendJson<unknown>("/auth/me");
    return NextResponse.json(me);
  } catch (e) {
    if (e instanceof BackendError) {
      return NextResponse.json(e.body ?? { detail: "Backend error" }, { status: e.status });
    }
    return NextResponse.json({ detail: String(e) }, { status: 502 });
  }
}
