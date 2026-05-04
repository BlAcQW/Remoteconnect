"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTechnicianChannel } from "./TechnicianChannel";

interface Entry {
  name: string;
  kind: "file" | "dir" | "drive";
  size: number | null;
  mtime: number | null;
}

function newRequestId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function joinPath(base: string, child: string): string {
  if (!base || base === "" || base === "drives:") return child;
  // Drive entries already include their own trailing slash on Windows.
  if (child.endsWith(":\\") || child.endsWith(":/")) return child;
  // Use forward-slash heuristic for both Windows + POSIX since
  // Path() on the agent side normalizes either form.
  if (base.endsWith("\\") || base.endsWith("/")) return base + child;
  return `${base}/${child}`;
}

function parentOf(path: string): string {
  if (!path || path === "" || path === "drives:") return "";
  // Trim trailing separators.
  const trimmed = path.replace(/[\\/]+$/, "");
  const lastSlash = Math.max(trimmed.lastIndexOf("/"), trimmed.lastIndexOf("\\"));
  if (lastSlash <= 0) {
    // E.g. "C:" → drives:; "/" → ""
    return "drives:";
  }
  return trimmed.slice(0, lastSlash);
}

function formatBytes(n: number | null): string {
  if (n === null || n === undefined) return "";
  if (n < 1024) return `${n} B`;
  const kb = n / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  const mb = kb / 1024;
  if (mb < 1024) return `${mb.toFixed(1)} MB`;
  return `${(mb / 1024).toFixed(2)} GB`;
}

function formatTime(t: number | null): string {
  if (!t) return "";
  try {
    return new Date(t * 1000).toLocaleString();
  } catch {
    return "";
  }
}

export function FileBrowserPanel({ onClose }: { onClose: () => void }) {
  const channel = useTechnicianChannel();
  const [path, setPath] = useState<string>("drives:");
  const [pendingPath, setPendingPath] = useState<string>("drives:");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [draftAddress, setDraftAddress] = useState<string>("");
  const lastRequestRef = useRef<string | null>(null);
  const downloadBufRef = useRef<{
    filename: string;
    chunks: Uint8Array[];
    totalChunks: number | null;
  } | null>(null);

  const navigate = useCallback(
    (target: string) => {
      if (channel.status !== "open") return;
      const rid = newRequestId();
      lastRequestRef.current = rid;
      setLoading(true);
      setError(null);
      setPendingPath(target);
      channel.send({ type: "dir_list", request_id: rid, path: target });
    },
    [channel],
  );

  useEffect(() => {
    return channel.subscribe((m) => {
      if (m.type === "dir_list_response") {
        const rid = String(m.request_id ?? "");
        if (rid !== lastRequestRef.current) return;
        const list = Array.isArray(m.entries) ? (m.entries as Entry[]) : [];
        setEntries(list);
        const nextPath = String(m.path ?? "");
        setPath(nextPath || "drives:");
        setDraftAddress(nextPath || "");
        setError(m.error ? String(m.error) : null);
        setLoading(false);
      } else if (m.type === "file_chunk") {
        // Reuse existing file_chunk for downloads; we only listen when
        // we're actively downloading a single file.
        const buf = downloadBufRef.current;
        if (!buf) return;
        if (m.filename && String(m.filename) !== buf.filename) return;
        const idx = Number(m.chunk_index ?? 0);
        const total = Number(m.total_chunks ?? 0);
        const b64 = String(m.data_b64 ?? "");
        try {
          const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
          buf.chunks[idx] = bytes;
          buf.totalChunks = total;
        } catch {
          /* ignore corrupt chunk */
        }
      } else if (m.type === "file_download_complete") {
        const buf = downloadBufRef.current;
        if (!buf || (m.filename && String(m.filename) !== buf.filename)) return;
        // Force a fresh ArrayBuffer-backed view per chunk so we don't trip
        // TypeScript's BlobPart constraint when an environment hands us a
        // SharedArrayBuffer-backed Uint8Array.
        const parts: BlobPart[] = buf.chunks
          .filter(Boolean)
          .map((c) => new Uint8Array(c));
        const blob = new Blob(parts, { type: "application/octet-stream" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = buf.filename;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        downloadBufRef.current = null;
        setDownloading(null);
      } else if (m.type === "file_download_error") {
        const buf = downloadBufRef.current;
        if (!buf || (m.filename && String(m.filename) !== buf.filename)) return;
        setError(`download failed: ${String(m.reason ?? "unknown")}`);
        downloadBufRef.current = null;
        setDownloading(null);
      }
    });
  }, [channel]);

  // Auto-fetch top level on mount.
  useEffect(() => {
    navigate("drives:");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function onEntryClick(e: Entry) {
    if (e.kind === "file") {
      // Trigger download via existing file_download_request flow with
      // an absolute path. Aggregate chunks until file_download_complete.
      if (downloading || channel.status !== "open") return;
      const target = joinPath(path === "drives:" ? "" : path, e.name);
      downloadBufRef.current = {
        filename: e.name,
        chunks: [],
        totalChunks: null,
      };
      setDownloading(e.name);
      setError(null);
      channel.send({
        type: "file_download_request",
        absolute_path: target,
        filename: e.name,
      });
      return;
    }
    // dir / drive — navigate into it
    const target =
      e.kind === "drive"
        ? e.name
        : joinPath(path === "drives:" ? "" : path, e.name);
    navigate(target);
  }

  function onUp() {
    if (path === "drives:" || !path) return;
    navigate(parentOf(path));
  }

  function onAddressSubmit(ev: React.FormEvent) {
    ev.preventDefault();
    const v = draftAddress.trim();
    navigate(v || "drives:");
  }

  return (
    <section className="rounded-lg border border-border bg-surface flex flex-col h-[28rem] w-full max-w-3xl">
      <header className="px-4 py-2.5 border-b border-border flex items-center justify-between">
        <span className="text-xs font-mono uppercase tracking-wider text-muted">
          Files
        </span>
        <button
          onClick={onClose}
          aria-label="Close file browser"
          className="text-muted hover:text-gray-200 text-xs"
        >
          ×
        </button>
      </header>
      <div className="px-3 py-2 border-b border-border flex gap-2 items-center">
        <button
          onClick={onUp}
          disabled={path === "drives:" || loading}
          title="Up"
          className="rounded-md border border-border text-xs px-2 py-1 hover:border-accent/50 hover:text-accent transition disabled:opacity-40"
        >
          ↑
        </button>
        <form onSubmit={onAddressSubmit} className="flex-1 flex gap-2">
          <input
            value={draftAddress}
            onChange={(e) => setDraftAddress(e.target.value)}
            placeholder="path (or empty for drives)"
            className="flex-1 rounded-md bg-bg border border-border px-2.5 py-1.5 text-sm font-mono focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
          />
          <button
            type="submit"
            disabled={loading || channel.status !== "open"}
            className="rounded-md border border-border text-xs px-3 py-1.5 hover:border-accent/50 hover:text-accent transition disabled:opacity-40"
          >
            Go
          </button>
        </form>
      </div>
      {error ? (
        <div className="px-3 py-2 text-xs text-red-300 border-b border-danger/30 bg-danger/10">
          {error}
        </div>
      ) : null}
      <div className="flex-1 overflow-auto">
        {loading ? (
          <p className="text-muted text-xs italic px-3 py-4">
            Loading {pendingPath || "drives"}…
          </p>
        ) : entries.length === 0 ? (
          <p className="text-muted text-xs italic px-3 py-4">empty</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-surface">
              <tr className="text-xs font-mono uppercase tracking-wider text-muted">
                <th className="px-2 py-1.5 text-left">Name</th>
                <th className="px-2 py-1.5 text-right">Size</th>
                <th className="px-2 py-1.5 text-left">Modified</th>
                <th className="px-2 py-1.5 text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.name} className="border-t border-border/60 hover:bg-bg/40">
                  <td
                    className="px-2 py-1 truncate max-w-[18rem] cursor-pointer"
                    onClick={() => onEntryClick(e)}
                  >
                    <span
                      className={
                        e.kind === "file"
                          ? "text-gray-200"
                          : "text-accent"
                      }
                    >
                      {e.kind === "dir" || e.kind === "drive" ? "📁 " : "📄 "}
                      {e.name}
                    </span>
                  </td>
                  <td className="px-2 py-1 font-mono text-xs text-muted text-right">
                    {formatBytes(e.size)}
                  </td>
                  <td className="px-2 py-1 text-xs text-muted">{formatTime(e.mtime)}</td>
                  <td className="px-2 py-1 text-right">
                    {e.kind === "file" ? (
                      <button
                        onClick={() => onEntryClick(e)}
                        disabled={downloading !== null || channel.status !== "open"}
                        className="rounded-md border border-border text-xs px-2 py-0.5 hover:border-accent/50 hover:text-accent transition disabled:opacity-40"
                      >
                        {downloading === e.name ? "…" : "Download"}
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
