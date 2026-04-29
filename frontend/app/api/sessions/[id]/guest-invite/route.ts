import { NextResponse } from "next/server";
import { BackendError, backendJson } from "@/lib/server-api";

export async function POST(_req: Request, ctx: { params: { id: string } }) {
  try {
    const result = await backendJson<unknown>(
      `/sessions/${encodeURIComponent(ctx.params.id)}/guest-invite`,
      { method: "POST" },
    );
    return NextResponse.json(result);
  } catch (e) {
    if (e instanceof BackendError) {
      return NextResponse.json(e.body ?? { detail: "Backend error" }, { status: e.status });
    }
    return NextResponse.json({ detail: String(e) }, { status: 502 });
  }
}
