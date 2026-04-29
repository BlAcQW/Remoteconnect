import { NextResponse } from "next/server";
import { BackendError, backendJson } from "@/lib/server-api";
import type { MeetingToken } from "@/lib/types";

export async function GET(req: Request, ctx: { params: { id: string } }) {
  const url = new URL(req.url);
  const role = url.searchParams.get("role") ?? "technician";
  if (role !== "technician" && role !== "agent") {
    return NextResponse.json({ detail: "Invalid role" }, { status: 400 });
  }
  try {
    const token = await backendJson<MeetingToken>(
      `/sessions/${encodeURIComponent(ctx.params.id)}/meeting-token?role=${role}`,
    );
    return NextResponse.json(token);
  } catch (e) {
    if (e instanceof BackendError) {
      return NextResponse.json(e.body ?? { detail: "Backend error" }, { status: e.status });
    }
    return NextResponse.json({ detail: String(e) }, { status: 502 });
  }
}
