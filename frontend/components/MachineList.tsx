"use client";

import useSWR from "swr";
import type { Machine } from "@/lib/types";
import { ApiError, api } from "@/lib/client-api";
import { MachineCard } from "./MachineCard";

export function MachineList({ initial }: { initial: Machine[] }) {
  const { data, error, isLoading } = useSWR<Machine[]>("machines", api.machines, {
    refreshInterval: 10_000,
    revalidateOnFocus: true,
    fallbackData: initial,
  });

  if (error) {
    const msg = error instanceof ApiError ? error.message : String(error);
    return (
      <div className="rounded-lg border border-danger/40 bg-danger/10 p-4 text-sm text-red-300">
        Failed to load machines: {msg}
      </div>
    );
  }

  const machines = data ?? [];
  if (isLoading && machines.length === 0) {
    return <p className="text-sm text-muted">Loading machines…</p>;
  }

  if (machines.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-surface p-8 text-center">
        <p className="text-sm text-muted">No machines registered yet.</p>
        <p className="mt-2 text-xs font-mono text-muted">
          Run the agent on a machine to register it.
        </p>
      </div>
    );
  }

  const online = machines.filter((m) => m.is_online).length;

  return (
    <div className="space-y-4">
      <p className="text-xs font-mono uppercase tracking-wider text-muted">
        {machines.length} machine{machines.length === 1 ? "" : "s"} ·{" "}
        <span className="text-success">{online} online</span>
      </p>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {machines.map((m) => (
          <MachineCard key={m.id} machine={m} />
        ))}
      </div>
    </div>
  );
}
