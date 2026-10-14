"use client";

import { useEffect, useState } from "react";
import { useTechnicianChannel } from "./TechnicianChannel";

type StatusInfo = {
  relayServer: string;
  connectedAt: number | null;
  messagesSent: number;
  messagesReceived: number;
  softwareVersion: string;
  lastError: string | null;
};

function useElapsed(connectedAt: number | null): string {
  const [elapsed, setElapsed] = useState("");

  useEffect(() => {
    if (!connectedAt) return;
    function update() {
      const secs = Math.floor((Date.now() - connectedAt!) / 1000);
      const h = Math.floor(secs / 3600);
      const m = Math.floor((secs % 3600) / 60);
      const s = secs % 60;
      setElapsed(
        h > 0
          ? `${h}h ${String(m).padStart(2, "0")}m ${String(s).padStart(2, "0")}s`
          : `${String(m).padStart(2, "0")}m ${String(s).padStart(2, "0")}s`,
      );
    }
    update();
    const id = window.setInterval(update, 1000);
    return () => window.clearInterval(id);
  }, [connectedAt]);

  return elapsed;
}

export function StatusPanel({
  onClose,
  channelStatus,
  sessionId,
}: {
  onClose: () => void;
  channelStatus: string;
  sessionId: string;
}) {
  const channel = useTechnicianChannel();
  const [info, setInfo] = useState<StatusInfo>({
    relayServer: "—",
    connectedAt: null,
    messagesSent: 0,
    messagesReceived: 0,
    softwareVersion: "—",
    lastError: null,
  });

  useEffect(() => {
    return channel.subscribe((m) => {
      if (m.type === "status_info") {
        setInfo((prev) => ({
          relayServer: String(m.relay_server ?? prev.relayServer),
          connectedAt: typeof m.connected_at === "number" ? m.connected_at : prev.connectedAt,
          messagesSent: typeof m.messages_sent === "number" ? m.messages_sent : prev.messagesSent,
          messagesReceived: typeof m.messages_received === "number" ? m.messages_received : prev.messagesReceived,
          softwareVersion: String(m.software_version ?? prev.softwareVersion),
          lastError: m.last_error ? String(m.last_error) : prev.lastError,
        }));
      }
      // Track message counts from any message
      setInfo((prev) => ({ ...prev, messagesReceived: prev.messagesReceived + 1 }));
    });
  }, [channel]);

  // Patch send to count outbound
  useEffect(() => {
    if (channel.status === "open" && !info.connectedAt) {
      setInfo((prev) => ({ ...prev, connectedAt: Date.now() }));
      channel.send({ type: "status_info_get" });
    }
  }, [channel.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const elapsed = useElapsed(info.connectedAt);
  const connected = channelStatus === "open";

  const rows: { label: string; value: React.ReactNode }[] = [
    {
      label: "Connection",
      value: (
        <span className={`font-mono ${connected ? "text-green-400" : "text-red-400"}`}>
          {connected ? "Connected" : channelStatus === "reconnecting" ? "Reconnecting…" : "Disconnected"}
        </span>
      ),
    },
    { label: "Relay Server", value: <span className="font-mono text-gray-300">{info.relayServer}</span> },
    { label: "Session ID", value: <span className="font-mono text-gray-400 text-[11px] break-all">{sessionId}</span> },
    { label: "Time Connected", value: <span className="font-mono text-gray-300">{elapsed || "—"}</span> },
    { label: "Messages Sent", value: <span className="font-mono text-gray-300">{info.messagesSent}</span> },
    { label: "Messages Received", value: <span className="font-mono text-gray-300">{info.messagesReceived}</span> },
    { label: "Software Version", value: <span className="font-mono text-gray-300">{info.softwareVersion}</span> },
  ];

  return (
    <div className="rounded-lg border border-border bg-surface w-80 flex flex-col">
      <header className="flex items-center justify-between px-4 py-2.5 border-b border-border">
        <span className="text-xs font-mono uppercase tracking-wider text-muted">Status / Info</span>
        <button onClick={onClose} className="text-muted hover:text-gray-200 transition text-sm">✕</button>
      </header>

      <div className="p-4">
        <table className="w-full text-xs">
          <tbody className="divide-y divide-border/50">
            {rows.map((row) => (
              <tr key={row.label}>
                <td className="py-2 pr-3 text-muted whitespace-nowrap">{row.label}</td>
                <td className="py-2 text-right">{row.value}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {info.lastError && (
          <div className="mt-3 rounded-md border border-danger/40 bg-danger/10 px-3 py-2">
            <p className="text-xs text-muted mb-0.5">Last Error</p>
            <p className="text-xs text-red-300 font-mono break-words">{info.lastError}</p>
          </div>
        )}
      </div>
    </div>
  );
}
