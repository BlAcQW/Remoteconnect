import { NextResponse } from "next/server";
import { BackendError, backendJson } from "@/lib/server-api";

type Params = { params: Promise<{ id: string }> };

export async function DELETE(_req: Request, { params }: Params) {
  const { id } = await params;
  try {
    const result = await backendJson<{ status: string }>(
      `/machines/${encodeURIComponent(id)}`,
      { method: "DELETE" },
    );
    return NextResponse.json(result);
  } catch (e) {
    if (e instanceof BackendError) {
      return NextResponse.json(e.body ?? { detail: "Backend error" }, { status: e.status });
    }
    return NextResponse.json({ detail: String(e) }, { status: 502 });
  }
}
