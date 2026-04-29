import { NextRequest, NextResponse } from "next/server";
import { BackendError, backendJson } from "@/lib/server-api";

export async function POST(req: NextRequest) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON body" }, { status: 400 });
  }
  try {
    const result = await backendJson<unknown>("/wake/", {
      method: "POST",
      body: JSON.stringify(body),
    });
    return NextResponse.json(result);
  } catch (e) {
    if (e instanceof BackendError) {
      return NextResponse.json(e.body ?? { detail: "Backend error" }, { status: e.status });
    }
    return NextResponse.json({ detail: String(e) }, { status: 502 });
  }
}
