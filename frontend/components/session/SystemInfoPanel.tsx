"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTechnicianChannel } from "./TechnicianChannel";

interface SysInfo {
  captured_at: number;
  agent: { pid: number; executable: string };
  cpu: {
    logical_cores: number;
    physical_cores: number | null;
    frequency_mhz: number | null;
    max_frequency_mhz: number | null;
    model: string;
    load_pct: number;
  } | null;
  memory: {
    total_mb: number;
    available_mb: number;
    used_pct: number;
    swap_total_mb: number;
    swap_used_pct: number;
  } | null;
  disks: Array<{
    mount: string;
    device: string;
    fstype: string;
    total_gb: number;
    used_gb: number;
    used_pct: number;
  }>;
  network: Array<{
    name: string;
    mac: string | null;
    ipv4: string[];
    ipv6: string[];
    speed_mbps: number | null;
  }>;
  os: {
    system: string;
    release: string;
    version: string;
    platform: string;
    machine: string;
    hostname: string;
    python: string;
    uptime_s: number;
  } | null;
  extras: Record<string, string>;
  errors: Record<string, string>;
}

function newRequestId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function formatUptime(seconds: number): string {
  if (!seconds || seconds < 0) return "—";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

export function SystemInfoPanel({ onClose }: { onClose: () => void }) {
  const channel = useTechnicianChannel();
  const [info, setInfo] = useState<SysInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const ridRef = useRef<string | null>(null);

  const refresh = useCallback(() => {
    if (channel.status !== "open" || loading) return;
    const rid = newRequestId();
    ridRef.current = rid;
    setLoading(true);
    setError(null);
    channel.send({ type: "sysinfo_get", request_id: rid });
  }, [channel, loading]);

  useEffect(() => {
    return channel.subscribe((m) => {
      if (m.type !== "sysinfo_response") return;
      const rid = String(m.request_id ?? "");
      if (rid !== ridRef.current) return;
      setLoading(false);
      if (m.error) {
        setError(String(m.error));
        return;
      }
      setInfo(m.info as SysInfo);
    });
  }, [channel]);

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <section className="rounded-lg border border-border bg-surface flex flex-col h-[28rem] w-full max-w-3xl">
      <header className="px-4 py-2.5 border-b border-border flex items-center justify-between">
        <span className="text-xs font-mono uppercase tracking-wider text-muted">
          System info
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
            aria-label="Close system info"
            className="text-muted hover:text-gray-200 text-xs"
          >
            ×
          </button>
        </div>
      </header>
      <div className="flex-1 overflow-auto p-3 text-sm">
        {error ? (
          <p className="text-xs text-red-300 border border-danger/30 bg-danger/10 rounded px-3 py-2">
            {error}
          </p>
        ) : !info ? (
          <p className="text-muted text-xs italic">
            {loading ? "Reading device…" : "No data."}
          </p>
        ) : (
          <div className="space-y-4">
            <Section title="OS">
              {info.os ? (
                <Grid>
                  <Row k="Hostname" v={info.os.hostname} />
                  <Row k="Platform" v={info.os.platform} />
                  <Row k="Machine" v={info.os.machine} />
                  <Row k="Uptime" v={formatUptime(info.os.uptime_s)} />
                </Grid>
              ) : null}
              {Object.keys(info.extras).length > 0 ? (
                <Grid>
                  {Object.entries(info.extras).map(([k, v]) => (
                    <Row key={k} k={k} v={v} />
                  ))}
                </Grid>
              ) : null}
            </Section>
            <Section title="CPU">
              {info.cpu ? (
                <Grid>
                  <Row k="Model" v={info.cpu.model} />
                  <Row
                    k="Cores"
                    v={`${info.cpu.physical_cores ?? "?"} physical / ${info.cpu.logical_cores} logical`}
                  />
                  <Row
                    k="Frequency"
                    v={
                      info.cpu.frequency_mhz
                        ? `${info.cpu.frequency_mhz} MHz` +
                          (info.cpu.max_frequency_mhz
                            ? ` (max ${info.cpu.max_frequency_mhz})`
                            : "")
                        : "—"
                    }
                  />
                  <Row k="Load now" v={`${info.cpu.load_pct.toFixed(1)} %`} />
                </Grid>
              ) : null}
            </Section>
            <Section title="Memory">
              {info.memory ? (
                <Grid>
                  <Row
                    k="RAM"
                    v={`${info.memory.total_mb} MB total · ${info.memory.available_mb} MB free · ${info.memory.used_pct.toFixed(1)} % used`}
                  />
                  <Row
                    k="Swap"
                    v={`${info.memory.swap_total_mb} MB total · ${info.memory.swap_used_pct.toFixed(1)} % used`}
                  />
                </Grid>
              ) : null}
            </Section>
            <Section title="Disks">
              {info.disks.length === 0 ? (
                <p className="text-muted text-xs italic">No disks reported.</p>
              ) : (
                <table className="w-full text-xs">
                  <thead className="text-muted font-mono uppercase">
                    <tr>
                      <th className="text-left py-1">Mount</th>
                      <th className="text-left py-1">Device</th>
                      <th className="text-left py-1">FS</th>
                      <th className="text-right py-1">Total GB</th>
                      <th className="text-right py-1">Used %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {info.disks.map((d) => (
                      <tr key={d.mount} className="border-t border-border/60">
                        <td className="py-1 font-mono">{d.mount}</td>
                        <td className="py-1 font-mono">{d.device}</td>
                        <td className="py-1 font-mono">{d.fstype}</td>
                        <td className="py-1 font-mono text-right">{d.total_gb}</td>
                        <td className="py-1 font-mono text-right">{d.used_pct.toFixed(0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Section>
            <Section title="Network">
              {info.network.length === 0 ? (
                <p className="text-muted text-xs italic">No active interfaces.</p>
              ) : (
                <div className="space-y-2">
                  {info.network.map((n) => (
                    <div
                      key={n.name}
                      className="rounded-md border border-border/60 px-3 py-2"
                    >
                      <div className="flex items-baseline justify-between">
                        <span className="font-mono text-sm">{n.name}</span>
                        <span className="text-muted text-xs font-mono">{n.mac ?? ""}</span>
                      </div>
                      {n.ipv4.length > 0 ? (
                        <div className="text-xs font-mono text-muted mt-1">
                          IPv4: {n.ipv4.join(", ")}
                        </div>
                      ) : null}
                      {n.ipv6.length > 0 ? (
                        <div className="text-xs font-mono text-muted">
                          IPv6: {n.ipv6.slice(0, 2).join(", ")}
                          {n.ipv6.length > 2 ? ` (+${n.ipv6.length - 2})` : ""}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              )}
            </Section>
            {Object.keys(info.errors).length > 0 ? (
              <Section title="Collection errors">
                <ul className="text-xs text-red-300 list-disc pl-5">
                  {Object.entries(info.errors).map(([k, v]) => (
                    <li key={k}>
                      <span className="font-mono">{k}:</span> {v}
                    </li>
                  ))}
                </ul>
              </Section>
            ) : null}
          </div>
        )}
      </div>
    </section>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-xs font-mono uppercase tracking-wider text-accent mb-1.5">
        {title}
      </h3>
      <div>{children}</div>
    </div>
  );
}

function Grid({ children }: { children: React.ReactNode }) {
  return (
    <dl className="grid grid-cols-[10rem_1fr] gap-x-4 gap-y-1 text-sm">
      {children}
    </dl>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <>
      <dt className="text-muted text-xs uppercase font-mono tracking-wider self-center">
        {k}
      </dt>
      <dd className="text-gray-200 font-mono text-xs break-all">{v ?? "—"}</dd>
    </>
  );
}
