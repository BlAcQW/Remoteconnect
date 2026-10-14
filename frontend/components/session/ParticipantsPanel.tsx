"use client";

import { useEffect, useState } from "react";
import { useTechnicianChannel } from "./TechnicianChannel";

type ConnectionType = "desktop" | "mobile" | "unknown";
type ParticipantRole = "host" | "viewer" | "technician";

type Participant = {
  id: string;
  name: string;
  role: ParticipantRole;
  connectionType: ConnectionType;
  connectedAt: number | null;
};

function ConnectionIcon({ type }: { type: ConnectionType }) {
  if (type === "mobile") {
    return (
      <svg className="w-3.5 h-3.5 text-muted" fill="currentColor" viewBox="0 0 24 24">
        <path d="M17 2H7C5.9 2 5 2.9 5 4v16c0 1.1.9 2 2 2h10c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H7V4h10v12zm-5 4c-.55 0-1-.45-1-1s.45-1 1-1 1 .45 1 1-.45 1-1 1z" />
      </svg>
    );
  }
  return (
    <svg className="w-3.5 h-3.5 text-muted" fill="currentColor" viewBox="0 0 24 24">
      <path d="M21 2H3c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h7l-2 3v1h8v-1l-2-3h7c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 12H3V4h18v10z" />
    </svg>
  );
}

function RoleBadge({ role }: { role: ParticipantRole }) {
  const styles: Record<ParticipantRole, string> = {
    host: "bg-accent/20 text-accent border-accent/40",
    technician: "bg-purple-900/40 text-purple-300 border-purple-500/40",
    viewer: "bg-border/50 text-muted border-border",
  };
  const labels: Record<ParticipantRole, string> = {
    host: "Host",
    technician: "Tech",
    viewer: "Viewer",
  };
  return (
    <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${styles[role]}`}>
      {labels[role]}
    </span>
  );
}

function useElapsedShort(connectedAt: number | null): string {
  const [elapsed, setElapsed] = useState("");
  useEffect(() => {
    if (!connectedAt) return;
    function update() {
      const secs = Math.floor((Date.now() - connectedAt!) / 1000);
      const m = Math.floor(secs / 60);
      const s = secs % 60;
      setElapsed(`${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`);
    }
    update();
    const id = window.setInterval(update, 1000);
    return () => window.clearInterval(id);
  }, [connectedAt]);
  return elapsed;
}

function ParticipantRow({ p }: { p: Participant }) {
  const elapsed = useElapsedShort(p.connectedAt);
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 border-b border-border/60 last:border-b-0">
      <div className="w-7 h-7 rounded-full bg-accent/20 border border-accent/30 flex items-center justify-center text-xs font-mono text-accent uppercase flex-shrink-0">
        {(p.name || "?")[0]}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-gray-200 truncate">{p.name || "Unknown"}</p>
        {elapsed && <p className="text-[10px] text-muted font-mono">{elapsed}</p>}
      </div>
      <div className="flex items-center gap-2 flex-shrink-0">
        <ConnectionIcon type={p.connectionType} />
        <RoleBadge role={p.role} />
      </div>
    </div>
  );
}

export function ParticipantsPanel({ onClose }: { onClose: () => void }) {
  const channel = useTechnicianChannel();
  const [participants, setParticipants] = useState<Participant[]>([]);

  useEffect(() => {
    return channel.subscribe((m) => {
      if (m.type === "participants_list") {
        if (Array.isArray(m.participants)) {
          setParticipants(m.participants as Participant[]);
        }
      }
      if (m.type === "participant_joined") {
        setParticipants((prev) => {
          const p = m.participant as Participant;
          if (prev.find((x) => x.id === p.id)) return prev;
          return [...prev, p];
        });
      }
      if (m.type === "participant_left") {
        setParticipants((prev) => prev.filter((x) => x.id !== String(m.participant_id)));
      }
    });
  }, [channel]);

  useEffect(() => {
    if (channel.status === "open") {
      channel.send({ type: "participants_get" });
    }
  }, [channel.status]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="rounded-lg border border-border bg-surface w-72 flex flex-col max-h-[400px]">
      <header className="flex items-center justify-between px-4 py-2.5 border-b border-border">
        <span className="text-xs font-mono uppercase tracking-wider text-muted">
          Participants
          {participants.length > 0 && (
            <span className="ml-2 px-1.5 py-0.5 rounded-full bg-accent/20 text-accent text-[10px]">
              {participants.length}
            </span>
          )}
        </span>
        <button onClick={onClose} className="text-muted hover:text-gray-200 transition text-sm">✕</button>
      </header>

      <div className="flex-1 overflow-y-auto">
        {participants.length === 0 ? (
          <p className="px-4 py-6 text-xs text-muted italic text-center">No participants detected</p>
        ) : (
          participants.map((p) => <ParticipantRow key={p.id} p={p} />)
        )}
      </div>
    </div>
  );
}
