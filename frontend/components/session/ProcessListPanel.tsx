"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTechnicianChannel } from "./TechnicianChannel";

interface ProcessRow {
  pid: number;
  name: string;
  user: string;
  cpu_pct: number;
  mem_mb: number;
  started_at: number;
  is_agent: boolean;
}

type SortKey = "name" | "pid" | "cpu_pct" | "mem_mb" | "user";

function newRequestId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export function ProcessListPanel({ onClose }: { onClose: () => void }) {
  const channel = useTechnicianChannel();
  const [rows, setRows] = useState<ProcessRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("mem_mb");
  const [sortDesc, setSortDesc] = useState(true);
  const [killingPid, setKillingPid] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const lastRequestRef = useRef<string | null>(null);

  const refresh = useCallback(() => {
    if (channel.status !== "open" || refreshing) return;
    const rid = newRequestId();
    lastRequestRef.current = rid;
    setRefreshing(true);
    channel.send({ type: "process_list", request_id: rid });
  }, [channel, refreshing]);

  useEffect(() => {
    return channel.subscribe((m) => {
      if (m.type === "process_list_response") {
        const rid = String(m.request_id ?? "");
        if (rid !== lastRequestRef.current) return;
        const procs = Array.isArray(m.processes) ? (m.processes as ProcessRow[]) : [];
        setRows(procs);
        setError(m.error ? String(m.error) : null);
        setRefreshing(false);
      } else if (m.type === "process_kill_response") {
        const ok = Boolean(m.ok);
        const err = m.error ? String(m.error) : null;
        setKillingPid(null);
        if (!ok && err) {
          setError(`kill failed: ${err}`);
        }
        // Refresh to reflect the killed process disappearing.
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
    let list = rows;
    if (f) {
      list = list.filter(
        (r) =>
          r.name.toLowerCase().includes(f) ||
          String(r.pid).includes(f) ||
          (r.user || "").toLowerCase().includes(f),
      );
    }
    const cmp = (a: ProcessRow, b: ProcessRow): number => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === "number" && typeof bv === "number") return av - bv;
      return String(av).localeCompare(String(bv));
    };
    const sorted = [...list].sort(cmp);
    if (sortDesc) sorted.reverse();
    return sorted;
  }, [rows, filter, sortKey, sortDesc]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDesc((v) => !v);
    } else {
      setSortKey(key);
      setSortDesc(true);
    }
  }

  function onKill(pid: number, name: string) {
    if (channel.status !== "open" || killingPid !== null) return;
    if (!window.confirm(`Kill ${name} (PID ${pid})?`)) return;
    const rid = newRequestId();
    setKillingPid(pid);
    setError(null);
    channel.send({ type: "process_kill", request_id: rid, pid, force: false });
  }

  return (
    <section className="rounded-lg border border-border bg-surface flex flex-col h-[28rem] w-full max-w-3xl">
      <header className="px-4 py-2.5 border-b border-border flex items-center justify-between">
        <span className="text-xs font-mono uppercase tracking-wider text-muted">
          Processes ({filtered.length}/{rows.length})
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={refresh}
            disabled={refreshing || channel.status !== "open"}
            className="text-xs font-mono uppercase tracking-wider text-muted hover:text-accent transition disabled:opacity-40"
          >
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
          <button
            onClick={onClose}
            aria-label="Close processes panel"
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
          placeholder="filter by name, pid, user…"
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
              <Th onClick={() => toggleSort("name")} active={sortKey === "name"} desc={sortDesc}>
                Name
              </Th>
              <Th onClick={() => toggleSort("pid")} active={sortKey === "pid"} desc={sortDesc}>
                PID
              </Th>
              <Th onClick={() => toggleSort("cpu_pct")} active={sortKey === "cpu_pct"} desc={sortDesc}>
                CPU %
              </Th>
              <Th onClick={() => toggleSort("mem_mb")} active={sortKey === "mem_mb"} desc={sortDesc}>
                Mem MB
              </Th>
              <Th onClick={() => toggleSort("user")} active={sortKey === "user"} desc={sortDesc}>
                User
              </Th>
              <th className="px-2 py-1.5 text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => (
              <tr key={r.pid} className="border-t border-border/60 hover:bg-bg/40">
                <td className="px-2 py-1 truncate max-w-[14rem]" title={r.name}>
                  {r.name}
                  {r.is_agent ? (
                    <span className="ml-1 text-[10px] font-mono uppercase text-accent">agent</span>
                  ) : null}
                </td>
                <td className="px-2 py-1 font-mono text-xs">{r.pid}</td>
                <td className="px-2 py-1 font-mono text-xs">{r.cpu_pct.toFixed(1)}</td>
                <td className="px-2 py-1 font-mono text-xs">{r.mem_mb.toFixed(0)}</td>
                <td className="px-2 py-1 truncate max-w-[8rem] text-xs" title={r.user}>
                  {r.user}
                </td>
                <td className="px-2 py-1 text-right">
                  <button
                    onClick={() => onKill(r.pid, r.name)}
                    disabled={r.is_agent || killingPid !== null || channel.status !== "open"}
                    className="rounded-md border border-danger/40 bg-danger/5 text-red-300 hover:bg-danger/15 transition px-2 py-0.5 text-xs disabled:opacity-30 disabled:cursor-not-allowed"
                  >
                    {killingPid === r.pid ? "…" : "Kill"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && !refreshing ? (
          <p className="text-muted text-xs italic px-3 py-4">No processes match the filter.</p>
        ) : null}
      </div>
    </section>
  );
}

function Th({
  active,
  desc,
  onClick,
  children,
}: {
  active: boolean;
  desc: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <th className="px-2 py-1.5 text-left">
      <button
        onClick={onClick}
        className={`hover:text-accent transition ${active ? "text-accent" : ""}`}
      >
        {children} {active ? (desc ? "↓" : "↑") : ""}
      </button>
    </th>
  );
}
