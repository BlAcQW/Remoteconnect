"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTechnicianChannel } from "./TechnicianChannel";

const CHUNK_SIZE = 64 * 1024; // matches agent DEFAULT_CHUNK_SIZE
const MAX_BYTES = 100 * 1024 * 1024; // matches backend MAX_TRANSFER_BYTES

type Direction = "upload" | "download";
type Status = "pending" | "in_progress" | "ok" | "rejected" | "error";

type Transfer = {
  id: string;
  filename: string;
  direction: Direction;
  size_bytes: number;
  bytes_done: number;
  total_chunks: number;
  chunks_done: number;
  status: Status;
  detail?: string;
};

type DownloadAccum = {
  filename: string;
  total: number;
  size: number;
  chunks: Map<number, Uint8Array>;
};

type Props = {
  sessionEnded: boolean;
};

export function FilePanel({ sessionEnded }: Props) {
  const channel = useTechnicianChannel();
  const [transfers, setTransfers] = useState<Transfer[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [downloadName, setDownloadName] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);
  const downloadsRef = useRef<Map<string, DownloadAccum>>(new Map());

  const updateTransfer = useCallback(
    (id: string, patch: Partial<Transfer>) =>
      setTransfers((prev) => prev.map((t) => (t.id === id ? { ...t, ...patch } : t))),
    [],
  );
  const findUploadByFilename = useCallback(
    (filename: string) =>
      setTransfers((prev) => {
        const found = prev.find(
          (t) => t.filename === filename && t.direction === "upload" && t.status !== "ok",
        );
        return found ? prev : prev;
      }),
    [],
  );

  // ── Listen for file_* responses from the agent (via the backend) ──────────
  useEffect(() => {
    findUploadByFilename;
    return channel.subscribe((msg) => {
      const t = String(msg.type ?? "");
      const filename = String((msg.filename as string) ?? "");
      if (!filename) return;

      if (t === "file_upload_ack") {
        const status = msg.status === "ok" ? "in_progress" : "rejected";
        setTransfers((prev) =>
          prev.map((tr) =>
            tr.direction === "upload" && tr.filename === filename && tr.status === "pending"
              ? { ...tr, status, detail: (msg.reason as string) ?? undefined }
              : tr,
          ),
        );
      } else if (t === "file_upload_complete") {
        setTransfers((prev) =>
          prev.map((tr) =>
            tr.direction === "upload" && tr.filename === filename
              ? {
                  ...tr,
                  status: "ok",
                  bytes_done: Number(msg.size_bytes ?? tr.size_bytes),
                  detail: msg.saved_path ? `saved: ${msg.saved_path}` : tr.detail,
                }
              : tr,
          ),
        );
      } else if (t === "file_chunk") {
        // Inbound download chunks
        const total = Number(msg.total_chunks ?? 0);
        const index = Number(msg.chunk_index ?? 0);
        const data = String(msg.data_b64 ?? "");
        let acc = downloadsRef.current.get(filename);
        if (!acc) {
          acc = { filename, total, size: 0, chunks: new Map() };
          downloadsRef.current.set(filename, acc);
          setTransfers((prev) => [
            ...prev,
            {
              id: `dl-${filename}-${Date.now()}`,
              filename,
              direction: "download",
              size_bytes: 0,
              bytes_done: 0,
              total_chunks: total,
              chunks_done: 0,
              status: "in_progress",
            },
          ]);
        }
        const bytes = b64ToBytes(data);
        acc.chunks.set(index, bytes);
        acc.size += bytes.length;
        setTransfers((prev) =>
          prev.map((tr) =>
            tr.direction === "download" && tr.filename === filename && tr.status === "in_progress"
              ? {
                  ...tr,
                  total_chunks: total,
                  chunks_done: acc!.chunks.size,
                  bytes_done: acc!.size,
                  size_bytes: acc!.size,
                }
              : tr,
          ),
        );
      } else if (t === "file_download_complete") {
        const acc = downloadsRef.current.get(filename);
        if (!acc) return;
        const ordered: ArrayBuffer[] = [];
        for (let i = 0; i < acc.total; i++) {
          const part = acc.chunks.get(i);
          if (!part) {
            updateTransfer(`dl-${filename}-pending`, { status: "error", detail: "missing chunk" });
            return;
          }
          // Copy each chunk into a fresh ArrayBuffer so it satisfies the BlobPart type
          // even when the source buffer is a SharedArrayBuffer-typed view.
          const ab = new ArrayBuffer(part.byteLength);
          new Uint8Array(ab).set(part);
          ordered.push(ab);
        }
        const blob = new Blob(ordered, { type: "application/octet-stream" });
        triggerSave(filename, blob);
        downloadsRef.current.delete(filename);
        setTransfers((prev) =>
          prev.map((tr) =>
            tr.direction === "download" && tr.filename === filename ? { ...tr, status: "ok" } : tr,
          ),
        );
      } else if (t === "file_download_error") {
        downloadsRef.current.delete(filename);
        setTransfers((prev) =>
          prev.map((tr) =>
            tr.direction === "download" && tr.filename === filename
              ? { ...tr, status: "error", detail: String(msg.reason ?? "error") }
              : tr,
          ),
        );
      }
    });
  }, [channel, updateTransfer, findUploadByFilename]);

  // ── Upload ───────────────────────────────────────────────────────────────
  const startUpload = useCallback(
    async (file: File) => {
      if (file.size > MAX_BYTES) {
        setTransfers((prev) => [
          ...prev,
          {
            id: `up-${file.name}-${Date.now()}`,
            filename: file.name,
            direction: "upload",
            size_bytes: file.size,
            bytes_done: 0,
            total_chunks: 0,
            chunks_done: 0,
            status: "rejected",
            detail: `> ${MAX_BYTES} bytes`,
          },
        ]);
        return;
      }

      const total = Math.max(1, Math.ceil(file.size / CHUNK_SIZE));
      const id = `up-${file.name}-${Date.now()}`;
      setTransfers((prev) => [
        ...prev,
        {
          id,
          filename: file.name,
          direction: "upload",
          size_bytes: file.size,
          bytes_done: 0,
          total_chunks: total,
          chunks_done: 0,
          status: "pending",
        },
      ]);

      const accepted = channel.send({
        type: "file_upload_start",
        filename: file.name,
        size_bytes: file.size,
        total_chunks: total,
      });
      if (!accepted) {
        updateTransfer(id, { status: "error", detail: "channel closed" });
        return;
      }

      const buf = new Uint8Array(await file.arrayBuffer());
      let chunksSent = 0;
      let bytesSent = 0;
      for (let i = 0; i < total; i++) {
        const start = i * CHUNK_SIZE;
        const end = Math.min(buf.length, start + CHUNK_SIZE);
        const slice = buf.subarray(start, end);
        const ok = channel.send({
          type: "file_chunk",
          filename: file.name,
          chunk_index: i,
          total_chunks: total,
          data_b64: bytesToB64(slice),
        });
        if (!ok) {
          updateTransfer(id, { status: "error", detail: "channel dropped mid-upload" });
          return;
        }
        chunksSent++;
        bytesSent = end;
        // Update progress in batches to avoid render storms.
        if (chunksSent % 4 === 0 || i === total - 1) {
          updateTransfer(id, { chunks_done: chunksSent, bytes_done: bytesSent });
        }
        // Yield occasionally so the UI can paint.
        if (chunksSent % 16 === 0) await Promise.resolve();
      }
      updateTransfer(id, { chunks_done: chunksSent, bytes_done: bytesSent });
    },
    [channel, updateTransfer],
  );

  function onPick(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (!files) return;
    for (const f of Array.from(files)) startUpload(f);
    e.target.value = "";
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragActive(false);
    if (sessionEnded) return;
    const files = e.dataTransfer.files;
    if (!files) return;
    for (const f of Array.from(files)) startUpload(f);
  }

  function onDownload() {
    const name = downloadName.trim();
    if (!name) return;
    setDownloadName("");
    setTransfers((prev) => [
      ...prev,
      {
        id: `dl-${name}-pending`,
        filename: name,
        direction: "download",
        size_bytes: 0,
        bytes_done: 0,
        total_chunks: 0,
        chunks_done: 0,
        status: "pending",
      },
    ]);
    channel.send({ type: "file_download_request", filename: name });
  }

  // ── Render ──────────────────────────────────────────────────────────────
  const disabled = sessionEnded || channel.status !== "open";

  return (
    <section className="rounded-lg border border-border bg-surface p-4">
      <div className="flex items-center justify-between gap-4 mb-3">
        <h2 className="text-sm font-mono uppercase tracking-wider text-muted">File transfer</h2>
        <span className="text-[10px] font-mono uppercase tracking-wider text-muted">
          ≤ 100 MiB · 64 KiB chunks
        </span>
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={onDrop}
        onClick={() => !disabled && inputRef.current?.click()}
        className={
          "rounded-md border-2 border-dashed transition cursor-pointer p-6 text-center text-sm " +
          (disabled
            ? "border-border text-muted cursor-not-allowed"
            : dragActive
            ? "border-accent bg-accent/5 text-accent"
            : "border-border text-muted hover:border-accent/40 hover:text-gray-300")
        }
      >
        {disabled ? "Channel offline" : "Drop files here, or click to choose — sends to remote"}
        <input
          ref={inputRef}
          type="file"
          multiple
          onChange={onPick}
          disabled={disabled}
          className="hidden"
        />
      </div>

      <div className="mt-4 flex items-center gap-2">
        <input
          value={downloadName}
          onChange={(e) => setDownloadName(e.target.value)}
          placeholder="filename in remote share to download"
          disabled={disabled}
          className="flex-1 rounded-md bg-bg border border-border px-2.5 py-1.5 text-sm font-mono focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-50"
        />
        <button
          onClick={onDownload}
          disabled={disabled || !downloadName.trim()}
          className="rounded-md border border-border text-sm px-3 py-1.5 hover:border-accent/50 hover:text-accent transition disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Pull
        </button>
      </div>

      {transfers.length > 0 ? (
        <ul className="mt-4 space-y-1.5 text-xs font-mono">
          {transfers
            .slice()
            .reverse()
            .map((t) => (
              <li key={t.id} className="flex items-center justify-between gap-3">
                <span className={statusColor(t.status)}>
                  {t.direction === "upload" ? "↑" : "↓"} {t.filename}
                </span>
                <span className="text-muted">
                  {pct(t)} · {t.status}
                  {t.detail ? ` · ${t.detail}` : ""}
                </span>
              </li>
            ))}
        </ul>
      ) : null}
    </section>
  );
}

function pct(t: Transfer): string {
  if (t.size_bytes <= 0) return `${t.chunks_done}/${t.total_chunks || "?"}`;
  const ratio = Math.min(1, t.bytes_done / t.size_bytes);
  return `${(ratio * 100).toFixed(0)}% (${formatSize(t.bytes_done)}/${formatSize(t.size_bytes)})`;
}

function formatSize(n: number): string {
  if (n < 1024) return `${n}B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}KiB`;
  return `${(n / 1024 / 1024).toFixed(1)}MiB`;
}

function statusColor(s: Status): string {
  if (s === "ok") return "text-success";
  if (s === "rejected" || s === "error") return "text-red-400";
  return "text-gray-300";
}

function bytesToB64(bytes: Uint8Array): string {
  // chunk-string encoding to avoid call-stack overflow on large arrays
  let bin = "";
  const STEP = 0x8000;
  for (let i = 0; i < bytes.length; i += STEP) {
    bin += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + STEP)));
  }
  return btoa(bin);
}

function b64ToBytes(b64: string): Uint8Array {
  if (!b64) return new Uint8Array(0);
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function triggerSave(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}
