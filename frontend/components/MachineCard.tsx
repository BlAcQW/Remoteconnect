"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/client-api";
import type { Machine } from "@/lib/types";

function relativeTime(iso: string | null): string {
  if (!iso) return "never";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "never";
  const delta = Math.max(0, Date.now() - t);
  const s = Math.floor(delta / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

function osLabel(os: string | null): string {
  if (!os) return "?";
  const v = os.toLowerCase();
  if (v.includes("win")) return "Windows";
  if (v.includes("mac") || v.includes("darwin")) return "macOS";
  if (v.includes("linux")) return "Linux";
  return os;
}

export function MachineCard({ machine }: { machine: Machine }) {
  const router = useRouter();
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onConnect() {
    setError(null);
    setConnecting(true);
    try {
      const session = await api.createSession(machine.id);
      router.push(`/session/${session.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : (err as Error).message);
      setConnecting(false);
    }
  }

  return (
    <div className="rounded-lg border border-border bg-surface p-5 hover:border-accent/40 transition">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              className={`inline-block w-2 h-2 rounded-full ${
                machine.is_online ? "bg-success shadow-glow" : "bg-muted"
              }`}
              title={machine.is_online ? "Online" : "Offline"}
            />
            <h3 className="font-medium truncate">{machine.name}</h3>
          </div>
          <p className="mt-1 text-xs font-mono text-muted truncate" title={machine.id}>
            {machine.id.slice(0, 8)}…
          </p>
        </div>
        <span className="text-[10px] uppercase tracking-wider text-muted px-1.5 py-0.5 rounded border border-border">
          {osLabel(machine.os)}
        </span>
      </div>

      <dl className="mt-4 space-y-1.5 text-sm">
        <div className="flex justify-between gap-2">
          <dt className="text-muted">Hostname</dt>
          <dd className="truncate">{machine.hostname || "—"}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted">IP</dt>
          <dd className="font-mono">{machine.ip_address || "—"}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted">Last seen</dt>
          <dd>{relativeTime(machine.last_seen)}</dd>
        </div>
      </dl>

      {error ? (
        <p className="mt-3 text-xs text-red-300 border border-danger/40 bg-danger/10 rounded px-2 py-1">
          {error}
        </p>
      ) : null}

      <button
        onClick={onConnect}
        disabled={!machine.is_online || connecting}
        className="mt-5 w-full rounded-md bg-accent text-bg font-medium py-2 text-sm hover:shadow-glow transition disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {connecting ? "Starting session…" : machine.is_online ? "Connect" : "Offline"}
      </button>
    </div>
  );
}
