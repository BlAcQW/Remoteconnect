import { NextResponse } from "next/server";
import { BackendError, backendJson } from "@/lib/server-api";
import type { Machine } from "@/lib/types";

export async function GET() {
  try {
    const machines = await backendJson<Machine[]>("/machines/");
    return NextResponse.json(machines);
  } catch (e) {
    if (e instanceof BackendError) {
      return NextResponse.json(e.body ?? { detail: "Backend error" }, { status: e.status });
    }
    return NextResponse.json({ detail: String(e) }, { status: 502 });
  }
}
