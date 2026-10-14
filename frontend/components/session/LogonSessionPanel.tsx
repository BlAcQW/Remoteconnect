"use client";

import { useEffect, useState } from "react";
import { useTechnicianChannel } from "./TechnicianChannel";

type LogonSession = { id: string; username: string; type: "ghostmode" | "active" };

export function LogonSessionPanel({ onClose }: { onClose: () => void }) {
  const channel = useTechnicianChannel();
  const [sessions, setSessions] = useState<LogonSession[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [shareDesktop, setShareDesktop] = useState(false);

  useEffect(() => {
    return channel.subscribe((m) => {
      if (m.type === "logon_sessions") {
        if (Array.isArray(m.sessions)) {
          setSessions(m.sessions as LogonSession[]);
        }
        if (m.selected) setSelected(String(m.selected));
        if (typeof m.share_desktop === "boolean") setShareDesktop(m.share_desktop);
      }
    });
  }, [channel]);

  useEffect(() => {
    if (channel.status === "open") {
      channel.send({ type: "logon_sessions_get" });
    }
  }, [channel.status]); // eslint-disable-line react-hooks/exhaustive-deps

  function selectSession(id: string) {
    setSelected(id);
    channel.send({ type: "logon_session_select", session_id: id });
  }

  function toggleShareDesktop() {
    const next = !shareDesktop;
    setShareDesktop(next);
    channel.send({ type: "share_desktop_set", enabled: next });
  }

  const disabled = channel.status !== "open";

  return (
    <div className="rounded-lg border border-border bg-surface w-72 flex flex-col">
      <header className="flex items-center justify-between px-4 py-2.5 border-b border-border">
        <span className="text-xs font-mono uppercase tracking-wider text-muted">Logon Session</span>
        <button onClick={onClose} className="text-muted hover:text-gray-200 transition text-sm">✕</button>
      </header>

      <div className="p-4 space-y-4">
        <div className="space-y-2">
          <p className="text-xs text-muted font-mono uppercase tracking-wider">Select Session</p>
          {sessions.length === 0 ? (
            <p className="text-xs text-muted italic">No sessions detected</p>
          ) : (
            <div className="space-y-1.5">
              {sessions.map((s) => (
                <button
                  key={s.id}
                  onClick={() => selectSession(s.id)}
                  disabled={disabled}
                  className={
                    "w-full flex items-center justify-between rounded-md border px-3 py-2 text-sm transition disabled:opacity-40 " +
                    (selected === s.id
                      ? "border-accent/60 bg-accent/20 text-accent"
                      : "border-border text-gray-300 hover:border-accent/50")
                  }
                >
                  <span>{s.username || "Unknown"}</span>
                  <span
                    className={
                      "text-xs font-mono px-1.5 py-0.5 rounded " +
                      (s.type === "ghostmode"
                        ? "bg-purple-900/50 text-purple-300"
                        : "bg-green-900/50 text-green-300")
                    }
                  >
                    {s.type === "ghostmode" ? "Ghost" : "Active"}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="border-t border-border pt-3">
          <button
            onClick={toggleShareDesktop}
            disabled={disabled}
            className={
              "w-full flex items-center justify-between rounded-md border px-3 py-2 text-sm transition disabled:opacity-40 " +
              (shareDesktop
                ? "border-accent/60 bg-accent/20 text-accent"
                : "border-border text-gray-300 hover:border-accent/50")
            }
          >
            <span>Share My Desktop</span>
            <span
              className={
                "text-xs font-mono px-1.5 py-0.5 rounded " +
                (shareDesktop ? "bg-accent/30 text-accent" : "bg-border/50 text-muted")
              }
            >
              {shareDesktop ? "ON" : "OFF"}
            </span>
          </button>
        </div>
      </div>
    </div>
  );
}
