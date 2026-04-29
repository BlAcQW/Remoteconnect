"use client";

import { useEffect, useRef, useState } from "react";

type Status = "connecting" | "open" | "closed" | "rejected";

export function GuestViewer({ token }: { token: string }) {
  const wsRef = useRef<WebSocket | null>(null);
  const [status, setStatus] = useState<Status>("connecting");
  const [reason, setReason] = useState<string | null>(null);

  useEffect(() => {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${location.host}/ws/guest/${encodeURIComponent(token)}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;
    setStatus("connecting");
    ws.onopen = () => setStatus("open");
    ws.onclose = (ev) => {
      if (ev.code === 1008) {
        setStatus("rejected");
        setReason("Invite is expired or invalid.");
      } else {
        setStatus("closed");
      }
    };
    ws.onerror = () => {
      // onclose follows; defer rendering decisions to that.
    };
    return () => {
      try {
        ws.close();
      } catch {
        /* noop */
      }
      wsRef.current = null;
    };
  }, [token]);

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-border bg-surface p-4 text-sm">
        <div className="flex items-center gap-3">
          <span
            className={`inline-block w-2 h-2 rounded-full ${
              status === "open"
                ? "bg-success shadow-glow"
                : status === "rejected"
                ? "bg-danger"
                : "bg-muted"
            }`}
          />
          <span className="font-mono text-xs uppercase tracking-wider text-muted">
            {status === "open" ? "linked" : status}
          </span>
        </div>
        <p className="mt-3 text-muted">
          You're watching this RemoteConnect session as a guest. You cannot send
          input, receive files, or extend the session — the link expires
          automatically.
        </p>
        {reason ? <p className="mt-2 text-red-300">{reason}</p> : null}
      </div>

      <div className="rounded-lg border border-dashed border-border bg-surface/40 p-12 text-center">
        <p className="text-sm text-muted">
          Live remote video isn't yet wired into the guest viewer in this build —
          the WebSocket channel is established and ready.
        </p>
        <p className="mt-2 text-xs font-mono text-muted">
          Future: render the same Daily.co track that the technician sees.
        </p>
      </div>
    </div>
  );
}
