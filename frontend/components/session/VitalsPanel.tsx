"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTechnicianChannel } from "./TechnicianChannel";

interface Tick {
  ts: number;
  cpu_pct: number;
  mem_total_mb: number;
  mem_used_pct: number;
  swap_used_pct: number;
  disk_read_bytes?: number;
  disk_write_bytes?: number;
  net_recv_bytes?: number;
  net_sent_bytes?: number;
  error?: string;
}

const HISTORY_LEN = 60; // ~1 min at 1 Hz

export function VitalsPanel({ onClose }: { onClose: () => void }) {
  const channel = useTechnicianChannel();
  const [history, setHistory] = useState<Tick[]>([]);
  const [active, setActive] = useState(false);

  // Subscribe on open, unsubscribe on close.
  useEffect(() => {
    if (channel.status !== "open") return;
    channel.send({ type: "vitals_subscribe", interval_s: 1.0 });
    setActive(true);
    return () => {
      channel.send({ type: "vitals_unsubscribe" });
      setActive(false);
    };
  }, [channel]);

  useEffect(() => {
    return channel.subscribe((m) => {
      if (m.type !== "vitals_tick") return;
      const tick = m as unknown as Tick;
      setHistory((prev) => {
        const next = [...prev, tick];
        if (next.length > HISTORY_LEN) next.shift();
        return next;
      });
    });
  }, [channel]);

  const latest = history[history.length - 1];
  const cpuSeries = useMemo(() => history.map((t) => t.cpu_pct), [history]);
  const memSeries = useMemo(() => history.map((t) => t.mem_used_pct), [history]);

  // Net + disk are cumulative; convert to per-second rates.
  const { netRx, netTx, diskRead, diskWrite } = useMemo(() => {
    const rx: number[] = [];
    const tx: number[] = [];
    const dr: number[] = [];
    const dw: number[] = [];
    for (let i = 1; i < history.length; i++) {
      const a = history[i - 1];
      const b = history[i];
      const dt = Math.max(0.001, b.ts - a.ts);
      if (a.net_recv_bytes !== undefined && b.net_recv_bytes !== undefined) {
        rx.push(Math.max(0, (b.net_recv_bytes - a.net_recv_bytes) / dt));
      }
      if (a.net_sent_bytes !== undefined && b.net_sent_bytes !== undefined) {
        tx.push(Math.max(0, (b.net_sent_bytes - a.net_sent_bytes) / dt));
      }
      if (a.disk_read_bytes !== undefined && b.disk_read_bytes !== undefined) {
        dr.push(Math.max(0, (b.disk_read_bytes - a.disk_read_bytes) / dt));
      }
      if (a.disk_write_bytes !== undefined && b.disk_write_bytes !== undefined) {
        dw.push(Math.max(0, (b.disk_write_bytes - a.disk_write_bytes) / dt));
      }
    }
    return { netRx: rx, netTx: tx, diskRead: dr, diskWrite: dw };
  }, [history]);

  return (
    <section className="rounded-lg border border-border bg-surface flex flex-col h-[28rem] w-full max-w-3xl">
      <header className="px-4 py-2.5 border-b border-border flex items-center justify-between">
        <span className="text-xs font-mono uppercase tracking-wider text-muted">
          Vitals {active ? "(live)" : ""}
        </span>
        <button
          onClick={onClose}
          aria-label="Close vitals panel"
          className="text-muted hover:text-gray-200 text-xs"
        >
          ×
        </button>
      </header>
      <div className="flex-1 overflow-auto p-3 space-y-4">
        {history.length === 0 ? (
          <p className="text-muted text-xs italic">
            Subscribed — waiting for first tick…
          </p>
        ) : (
          <>
            <Stat
              title="CPU"
              value={`${latest?.cpu_pct?.toFixed(1) ?? 0} %`}
              unit="%"
              series={cpuSeries}
              max={100}
              color="#4ea1ff"
            />
            <Stat
              title="Memory"
              value={`${latest?.mem_used_pct?.toFixed(1) ?? 0} % of ${latest?.mem_total_mb ?? "?"} MB`}
              unit="%"
              series={memSeries}
              max={100}
              color="#9aa0a6"
            />
            <div className="grid grid-cols-2 gap-3">
              <Stat
                title="Disk read"
                value={formatRate(diskRead.at(-1) ?? 0)}
                series={diskRead}
                color="#34d399"
              />
              <Stat
                title="Disk write"
                value={formatRate(diskWrite.at(-1) ?? 0)}
                series={diskWrite}
                color="#fb923c"
              />
              <Stat
                title="Net rx"
                value={formatRate(netRx.at(-1) ?? 0)}
                series={netRx}
                color="#a78bfa"
              />
              <Stat
                title="Net tx"
                value={formatRate(netTx.at(-1) ?? 0)}
                series={netTx}
                color="#f472b6"
              />
            </div>
          </>
        )}
      </div>
    </section>
  );
}

function Stat({
  title,
  value,
  unit,
  series,
  max,
  color,
}: {
  title: string;
  value: string;
  unit?: string;
  series: number[];
  max?: number;
  color: string;
}) {
  return (
    <div className="rounded-md border border-border/60 bg-bg/40 px-3 py-2">
      <div className="flex items-baseline justify-between">
        <span className="text-xs font-mono uppercase tracking-wider text-muted">
          {title}
        </span>
        <span className="text-sm font-mono">{value}</span>
      </div>
      <Sparkline series={series} max={max} color={color} unit={unit} />
    </div>
  );
}

function Sparkline({
  series,
  max,
  color,
  unit: _unit,
}: {
  series: number[];
  max?: number;
  color: string;
  unit?: string;
}) {
  const w = 320;
  const h = 40;
  const ref = useRef<SVGSVGElement | null>(null);
  if (series.length < 2) {
    return (
      <svg ref={ref} viewBox={`0 0 ${w} ${h}`} className="mt-2 w-full h-10 block">
        <line x1="0" y1={h - 1} x2={w} y2={h - 1} stroke="#222" strokeWidth="1" />
      </svg>
    );
  }
  const ymax = Math.max(max ?? 0, ...series, 1);
  const step = w / (series.length - 1);
  const path = series
    .map((v, i) => {
      const x = i * step;
      const y = h - (v / ymax) * (h - 2) - 1;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg ref={ref} viewBox={`0 0 ${w} ${h}`} className="mt-2 w-full h-10 block">
      <path d={path} stroke={color} strokeWidth="1.5" fill="none" />
    </svg>
  );
}

function formatRate(bps: number): string {
  if (bps < 1024) return `${bps.toFixed(0)} B/s`;
  if (bps < 1024 * 1024) return `${(bps / 1024).toFixed(1)} KB/s`;
  if (bps < 1024 * 1024 * 1024) return `${(bps / 1024 / 1024).toFixed(2)} MB/s`;
  return `${(bps / 1024 / 1024 / 1024).toFixed(2)} GB/s`;
}
