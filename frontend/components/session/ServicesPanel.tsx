"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTechnicianChannel } from "./TechnicianChannel";

interface ServiceRow {
  name: string;
  display_name: string;
  status: string;
  start_type: string;
  pid: number | null;
  description: string;
  username: string;
}

type Verb = "start" | "stop" | "restart";

function newRequestId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

const RUNNING_STATUSES = new Set(["running", "active", "started"]);
const STOPPED_STATUSES = new Set(["stopped", "inactive", "dead"]);

function statusClass(status: string): string {
  const s = status.toLowerCase();
  if (RUNNING_STATUSES.has(s)) return "text-success";
  if (STOPPED_STATUSES.has(s)) return "text-muted";
  return "text-yellow-400";
}

export function ServicesPanel({ onClose }: { onClose: () => void }) {
  const channel = useTechnicianChannel();
  const [rows, setRows] = useState<ServiceRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState("");
  const [pendingVerb, setPendingVerb] = useState<{ name: string; verb: Verb } | null>(null);
  const lastListRequestRef = useRef<string | null>(null);

  const refresh = useCallback(() => {
    if (channel.status !== "open" || loading) return;
    const rid = newRequestId();
    lastListRequestRef.current = rid;
    setLoading(true);
    channel.send({ type: "service_list", request_id: rid });
  }, [channel, loading]);

  useEffect(() => {
    return channel.subscribe((m) => {
      if (m.type === "service_list_response") {
        const rid = String(m.request_id ?? "");
        if (rid !== lastListRequestRef.current) return;
        const list = Array.isArray(m.services) ? (m.services as ServiceRow[]) : [];
        setRows(list);
        setError(m.error ? String(m.error) : null);
        setLoading(false);
      } else if (m.type === "service_action_response") {
        const ok = Boolean(m.ok);
        const err = m.error ? String(m.error) : null;
        setPendingVerb(null);
        if (!ok && err) setError(`action failed: ${err}`);
        // Always refresh after an action so the row reflects new state.
        refresh();
      }
    });
  }, [channel, refresh]);

  // Auto-fetch on open.
  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filtered = useMemo(() => {
    const f = filter.trim().toLowerCase();
    if (!f) return rows;
    return rows.filter(
      (r) =>
        r.name.toLowerCase().includes(f) ||
        r.display_name.toLowerCase().includes(f) ||
        r.description.toLowerCase().includes(f),
    );
  }, [rows, filter]);

  function onAction(name: string, verb: Verb) {
    if (channel.status !== "open" || pendingVerb !== null) return;
    if (!window.confirm(`${verb} ${name}?`)) return;
    const rid = newRequestId();
    setPendingVerb({ name, verb });
    setError(null);
    channel.send({ type: "service_action", request_id: rid, service: name, verb });
  }

  return (
    <section className="rounded-lg border border-border bg-surface flex flex-col h-[28rem] w-full max-w-3xl">
      <header className="px-4 py-2.5 border-b border-border flex items-center justify-between">
        <span className="text-xs font-mono uppercase tracking-wider text-muted">
          Services ({filtered.length}/{rows.length})
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={refresh}
            disabled={loading || channel.status !== "open"}
            className="text-xs font-mono uppercase tracking-wider text-muted hover:text-accent transition disabled:opacity-40"
          >
            {loading ? "Refreshing…" : "Refresh"}
          </button>
          <button
            onClick={onClose}
            aria-label="Close services panel"
            className="text-muted hover:text-gray-200 text-xs"
          >
            ×
          </button>
        </div>
      </header>
      <div className="px-3 py-2 border-b border-border">
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="filter by name, display name, description…"
          className="w-full rounded-md bg-bg border border-border px-2.5 py-1.5 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
        />
      </div>
      {error ? (
        <div className="px-3 py-2 text-xs text-red-300 border-b border-danger/30 bg-danger/10">
          {error}
        </div>
      ) : null}
      <div className="flex-1 overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-surface">
            <tr className="text-xs font-mono uppercase tracking-wider text-muted">
              <th className="px-2 py-1.5 text-left">Service</th>
              <th className="px-2 py-1.5 text-left">Status</th>
              <th className="px-2 py-1.5 text-left">Start type</th>
              <th className="px-2 py-1.5 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => {
              const isPending = pendingVerb?.name === r.name;
              return (
                <tr key={r.name} className="border-t border-border/60 hover:bg-bg/40">
                  <td className="px-2 py-1 max-w-[16rem] truncate" title={r.description || r.display_name}>
                    <div className="font-mono">{r.display_name || r.name}</div>
                    {r.display_name && r.display_name !== r.name ? (
                      <div className="text-[10px] text-muted font-mono">{r.name}</div>
                    ) : null}
                  </td>
                  <td className={`px-2 py-1 font-mono text-xs uppercase ${statusClass(r.status)}`}>
                    {r.status}
                  </td>
                  <td className="px-2 py-1 font-mono text-xs text-muted">{r.start_type}</td>
                  <td className="px-2 py-1 text-right whitespace-nowrap">
                    <ActionButton
                      label="Start"
                      onClick={() => onAction(r.name, "start")}
                      disabled={isPending || pendingVerb !== null || channel.status !== "open"}
                      pending={isPending && pendingVerb?.verb === "start"}
                    />
                    <ActionButton
                      label="Stop"
                      onClick={() => onAction(r.name, "stop")}
                      disabled={isPending || pendingVerb !== null || channel.status !== "open"}
                      pending={isPending && pendingVerb?.verb === "stop"}
                      tone="danger"
                    />
                    <ActionButton
                      label="Restart"
                      onClick={() => onAction(r.name, "restart")}
                      disabled={isPending || pendingVerb !== null || channel.status !== "open"}
                      pending={isPending && pendingVerb?.verb === "restart"}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {filtered.length === 0 && !loading ? (
          <p className="text-muted text-xs italic px-3 py-4">No services match the filter.</p>
        ) : null}
      </div>
    </section>
  );
}

function ActionButton({
  label,
  onClick,
  disabled,
  pending,
  tone,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  pending?: boolean;
  tone?: "danger";
}) {
  const base = "rounded-md text-xs px-2 py-0.5 transition disabled:opacity-30 disabled:cursor-not-allowed ml-1";
  const styles =
    tone === "danger"
      ? "border border-danger/40 bg-danger/5 text-red-300 hover:bg-danger/15"
      : "border border-border text-muted hover:border-accent/50 hover:text-accent";
  return (
    <button onClick={onClick} disabled={disabled} className={`${base} ${styles}`}>
      {pending ? "…" : label}
    </button>
  );
}
