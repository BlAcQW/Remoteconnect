"use client";

import { useEffect, useState } from "react";
import { useTechnicianChannel } from "./TechnicianChannel";

export function ClipboardPanel() {
  const channel = useTechnicianChannel();
  const [remote, setRemote] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    return channel.subscribe((m) => {
      if (m.type !== "clipboard_data") return;
      if (m.ok) {
        setRemote(String(m.text ?? ""));
        setError(null);
      } else {
        setError(String(m.reason ?? "clipboard unavailable on remote"));
      }
    });
  }, [channel]);

  function pull() {
    setError(null);
    channel.send({ type: "clipboard_get" });
  }

  function pushText() {
    if (!draft) return;
    channel.send({ type: "clipboard_set", text: draft });
  }

  return (
    <section className="rounded-lg border border-border bg-surface p-4 space-y-3">
      <header className="text-xs font-mono uppercase tracking-wider text-muted">Clipboard</header>

      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted">Remote → here</span>
          <button
            onClick={pull}
            disabled={channel.status !== "open"}
            className="text-xs font-mono uppercase tracking-wider rounded-md border border-border px-2 py-1 hover:border-accent/50 hover:text-accent transition disabled:opacity-40"
          >
            Pull
          </button>
        </div>
        <textarea
          readOnly
          value={remote ?? ""}
          placeholder="(remote clipboard contents will show here)"
          className="w-full h-20 rounded-md bg-bg border border-border px-2.5 py-1.5 text-xs font-mono resize-none"
        />
      </div>

      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted">Here → remote</span>
          <button
            onClick={pushText}
            disabled={channel.status !== "open" || !draft.trim()}
            className="text-xs font-mono uppercase tracking-wider rounded-md border border-border px-2 py-1 hover:border-accent/50 hover:text-accent transition disabled:opacity-40"
          >
            Push
          </button>
        </div>
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="text to send to remote clipboard"
          className="w-full h-20 rounded-md bg-bg border border-border px-2.5 py-1.5 text-xs font-mono resize-none"
        />
      </div>

      {error ? (
        <p className="text-xs text-red-300 border border-danger/40 bg-danger/10 rounded px-2 py-1">{error}</p>
      ) : null}
    </section>
  );
}
