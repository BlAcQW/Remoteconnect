"use client";

import { useEffect, useRef, useState } from "react";
import { useTechnicianChannel } from "./TechnicianChannel";

type Msg = { from: string; text: string; ts: number };

export function ChatPanel({ selfEmail }: { selfEmail: string }) {
  const channel = useTechnicianChannel();
  const [messages, setMessages] = useState<Msg[]>([]);
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    return channel.subscribe((m) => {
      if (m.type !== "chat") return;
      setMessages((prev) => [
        ...prev,
        {
          from: String(m.from_user ?? "?"),
          text: String(m.text ?? ""),
          ts: Number(m.ts ?? Date.now()),
        },
      ]);
    });
  }, [channel]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages.length]);

  function onSend(e: React.FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text) return;
    if (channel.send({ type: "chat", text, ts: Date.now() })) {
      setDraft("");
    }
  }

  return (
    <section className="rounded-lg border border-border bg-surface flex flex-col h-72">
      <header className="px-4 py-2.5 border-b border-border text-xs font-mono uppercase tracking-wider text-muted">
        Chat
      </header>
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-3 py-2 space-y-1 text-sm">
        {messages.length === 0 ? (
          <p className="text-muted text-xs italic">no messages yet</p>
        ) : (
          messages.map((m, i) => (
            <div key={i} className="flex gap-2">
              <span className={`font-mono text-[11px] uppercase ${m.from === selfEmail ? "text-accent" : "text-muted"}`}>
                {m.from === selfEmail ? "you" : m.from.split("@")[0]}
              </span>
              <span className="text-gray-200">{m.text}</span>
            </div>
          ))
        )}
      </div>
      <form onSubmit={onSend} className="border-t border-border px-3 py-2 flex gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="message…"
          disabled={channel.status !== "open"}
          className="flex-1 rounded-md bg-bg border border-border px-2.5 py-1.5 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={channel.status !== "open" || !draft.trim()}
          className="rounded-md border border-border text-sm px-3 py-1.5 hover:border-accent/50 hover:text-accent transition disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </section>
  );
}
