"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTechnicianChannel } from "./TechnicianChannel";

type Shell = "cmd" | "powershell" | "bash" | "sh";

interface Line {
  stream: "stdout" | "stderr" | "meta";
  text: string;
}

interface RunState {
  requestId: string;
  command: string;
  shell: Shell;
  startedAt: number;
  done: boolean;
  exitCode: number | null;
  error: string | null;
  lines: Line[];
}

const SHELL_OPTIONS: Shell[] = ["cmd", "powershell", "bash", "sh"];

function decodeB64(b64: string): string {
  try {
    return atob(b64);
  } catch {
    return "";
  }
}

function newRequestId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export function ShellPanel({ onClose }: { onClose: () => void }) {
  const channel = useTechnicianChannel();
  const [shell, setShell] = useState<Shell>("cmd");
  const [draft, setDraft] = useState("");
  const [runs, setRuns] = useState<RunState[]>([]);
  const activeRunRef = useRef<RunState | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    return channel.subscribe((m) => {
      if (m.type === "shell_chunk") {
        const rid = String(m.request_id ?? "");
        const stream = m.stream === "stderr" ? "stderr" : "stdout";
        const text = decodeB64(String(m.data_b64 ?? ""));
        setRuns((prev) =>
          prev.map((r) =>
            r.requestId === rid
              ? { ...r, lines: [...r.lines, { stream, text }] }
              : r,
          ),
        );
      } else if (m.type === "shell_complete") {
        const rid = String(m.request_id ?? "");
        const exit = m.exit_code === null || m.exit_code === undefined ? null : Number(m.exit_code);
        const err = m.error ? String(m.error) : null;
        const dur = Number(m.duration_ms ?? 0);
        setRuns((prev) =>
          prev.map((r) =>
            r.requestId === rid
              ? {
                  ...r,
                  done: true,
                  exitCode: exit,
                  error: err,
                  lines: [
                    ...r.lines,
                    {
                      stream: "meta",
                      text: `[exit=${exit ?? "?"} ${err ? `error=${err} ` : ""}${dur} ms]`,
                    },
                  ],
                }
              : r,
          ),
        );
        if (activeRunRef.current?.requestId === rid) {
          activeRunRef.current = null;
        }
      }
    });
  }, [channel]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight });
  }, [runs]);

  const activeRun = useMemo(() => runs.find((r) => !r.done) ?? null, [runs]);
  // Keep a ref in sync so the channel subscriber can clear it.
  activeRunRef.current = activeRun;

  function onRun(e: React.FormEvent) {
    e.preventDefault();
    const cmd = draft.trim();
    if (!cmd || activeRun) return;
    const requestId = newRequestId();
    const ok = channel.send({
      type: "shell_run",
      request_id: requestId,
      shell,
      command: cmd,
      timeout_s: 60,
    });
    if (!ok) return;
    setRuns((prev) => [
      ...prev,
      {
        requestId,
        command: cmd,
        shell,
        startedAt: Date.now(),
        done: false,
        exitCode: null,
        error: null,
        lines: [{ stream: "meta", text: `> [${shell}] ${cmd}` }],
      },
    ]);
    setDraft("");
  }

  function onCancel() {
    if (!activeRun) return;
    channel.send({ type: "shell_cancel", request_id: activeRun.requestId });
  }

  return (
    <section className="rounded-lg border border-border bg-surface flex flex-col h-[28rem] w-full max-w-3xl">
      <header className="px-4 py-2.5 border-b border-border flex items-center justify-between">
        <span className="text-xs font-mono uppercase tracking-wider text-muted">
          Hidden shell
        </span>
        <button
          onClick={onClose}
          aria-label="Close shell"
          className="text-muted hover:text-gray-200 text-xs"
        >
          ×
        </button>
      </header>
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-3 py-2 font-mono text-[12px] leading-snug bg-bg/40 whitespace-pre-wrap"
      >
        {runs.length === 0 ? (
          <p className="text-muted italic">No commands yet — try `whoami` or `ipconfig`.</p>
        ) : (
          runs.map((r) =>
            r.lines.map((l, i) => (
              <div
                key={`${r.requestId}-${i}`}
                className={
                  l.stream === "stderr"
                    ? "text-red-300"
                    : l.stream === "meta"
                    ? "text-accent"
                    : "text-gray-200"
                }
              >
                {l.text}
              </div>
            )),
          )
        )}
      </div>
      <form onSubmit={onRun} className="border-t border-border px-3 py-2 flex gap-2">
        <select
          value={shell}
          onChange={(e) => setShell(e.target.value as Shell)}
          disabled={!!activeRun || channel.status !== "open"}
          className="rounded-md bg-bg border border-border px-2 py-1.5 text-sm font-mono focus:border-accent focus:outline-none disabled:opacity-50"
        >
          {SHELL_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={activeRun ? "running…" : "command…"}
          disabled={!!activeRun || channel.status !== "open"}
          className="flex-1 rounded-md bg-bg border border-border px-2.5 py-1.5 text-sm font-mono focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-50"
        />
        {activeRun ? (
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-danger/50 bg-danger/10 text-red-300 hover:bg-danger/20 transition px-3 py-1.5 text-sm"
          >
            Cancel
          </button>
        ) : (
          <button
            type="submit"
            disabled={channel.status !== "open" || !draft.trim()}
            className="rounded-md border border-border text-sm px-3 py-1.5 hover:border-accent/50 hover:text-accent transition disabled:opacity-40"
          >
            Run
          </button>
        )}
      </form>
    </section>
  );
}
