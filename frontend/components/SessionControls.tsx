"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/client-api";

export function SessionControls({
  sessionId,
  status,
}: {
  sessionId: string;
  status: string;
}) {
  const router = useRouter();
  const [ending, setEnding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ended = status === "ended";

  async function onEnd() {
    setError(null);
    setEnding(true);
    try {
      await api.endSession(sessionId);
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : (err as Error).message);
    } finally {
      setEnding(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        onClick={onEnd}
        disabled={ended || ending}
        className="rounded-md border border-danger/60 bg-danger/10 text-red-300 hover:bg-danger/20 transition px-3 py-1.5 text-sm disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {ended ? "Ended" : ending ? "Ending…" : "End session"}
      </button>
      {error ? <p className="text-xs text-red-300">{error}</p> : null}
    </div>
  );
}
