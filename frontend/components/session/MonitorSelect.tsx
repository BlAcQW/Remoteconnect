"use client";

import { useEffect, useState } from "react";
import { useTechnicianChannel } from "./TechnicianChannel";

type Monitor = { index: number; width: number; height: number; left: number; top: number };

export function MonitorSelect() {
  const channel = useTechnicianChannel();
  const [monitors, setMonitors] = useState<Monitor[]>([]);
  const [selected, setSelected] = useState<number>(1);

  useEffect(() => {
    return channel.subscribe((m) => {
      if (m.type !== "monitor_list") return;
      if (Array.isArray(m.monitors)) {
        setMonitors(m.monitors as Monitor[]);
      }
      if (typeof m.selected === "number") {
        setSelected(m.selected);
      }
    });
  }, [channel]);

  // Probe monitor list on mount
  useEffect(() => {
    if (channel.status === "open") {
      channel.send({ type: "monitor_select", index: selected });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channel.status]);

  function pick(idx: number) {
    setSelected(idx);
    channel.send({ type: "monitor_select", index: idx });
  }

  if (monitors.length <= 1) return null;

  return (
    <section className="rounded-lg border border-border bg-surface p-4 space-y-2 text-sm">
      <header className="text-xs font-mono uppercase tracking-wider text-muted">Remote monitor</header>
      <select
        value={selected}
        onChange={(e) => pick(parseInt(e.target.value, 10))}
        className="w-full rounded-md bg-bg border border-border px-2 py-1 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
      >
        {monitors.map((m) => (
          <option key={m.index} value={m.index}>
            #{m.index} — {m.width}×{m.height}
          </option>
        ))}
      </select>
    </section>
  );
}
