"use client";

import { useRef, useState } from "react";
import { useTechnicianChannel } from "./TechnicianChannel";

type RecordState = "idle" | "recording" | "paused";

export function ScreenCapturePanel({ onClose }: { onClose: () => void }) {
  const channel = useTechnicianChannel();
  const [recordState, setRecordState] = useState<RecordState>("idle");
  const [captureFolder, setCaptureFolder] = useState<string>("");
  const [showFolderInput, setShowFolderInput] = useState(false);
  const [folderDraft, setFolderDraft] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  function takeScreenshot(dest: "clipboard" | "file") {
    channel.send({ type: "screenshot", dest });
    setStatus(dest === "clipboard" ? "Screenshot sent to clipboard." : "Screenshot saved to file.");
    setTimeout(() => setStatus(null), 3000);
  }

  function recordAction(action: "record" | "pause" | "stop") {
    if (action === "record") {
      channel.send({ type: "record_start", folder: captureFolder || undefined });
      setRecordState("recording");
    } else if (action === "pause") {
      channel.send({ type: "record_pause" });
      setRecordState("paused");
    } else {
      channel.send({ type: "record_stop" });
      setRecordState("idle");
      setStatus("Recording stopped.");
      setTimeout(() => setStatus(null), 3000);
    }
  }

  function applyFolder() {
    setCaptureFolder(folderDraft.trim());
    channel.send({ type: "capture_folder_set", folder: folderDraft.trim() });
    setShowFolderInput(false);
  }

  function openFolder() {
    channel.send({ type: "capture_folder_open" });
  }

  const disabled = channel.status !== "open";

  return (
    <div className="rounded-lg border border-border bg-surface w-80 flex flex-col">
      <header className="flex items-center justify-between px-4 py-2.5 border-b border-border">
        <span className="text-xs font-mono uppercase tracking-wider text-muted">Screen Capture</span>
        <button onClick={onClose} className="text-muted hover:text-gray-200 transition text-sm">✕</button>
      </header>

      <div className="p-4 space-y-4">
        {/* Screenshot */}
        <div className="space-y-2">
          <p className="text-xs text-muted font-mono uppercase tracking-wider">Screenshot</p>
          <div className="flex gap-2">
            <Btn disabled={disabled} onClick={() => takeScreenshot("clipboard")}>To Clipboard</Btn>
            <Btn disabled={disabled} onClick={() => takeScreenshot("file")}>To File</Btn>
          </div>
        </div>

        {/* Video recording */}
        <div className="space-y-2">
          <p className="text-xs text-muted font-mono uppercase tracking-wider">Record Video</p>
          <div className="flex gap-2">
            <Btn
              disabled={disabled || recordState === "recording"}
              onClick={() => recordAction("record")}
              active={recordState === "recording"}
            >
              {recordState === "recording" ? "● Rec" : "Record"}
            </Btn>
            <Btn
              disabled={disabled || recordState === "idle"}
              onClick={() => recordAction("pause")}
              active={recordState === "paused"}
            >
              {recordState === "paused" ? "Paused" : "Pause"}
            </Btn>
            <Btn
              disabled={disabled || recordState === "idle"}
              onClick={() => recordAction("stop")}
            >
              Stop
            </Btn>
          </div>
          {recordState !== "idle" && (
            <p className="text-xs text-accent">
              {recordState === "recording" ? "Recording…" : "Paused"}
            </p>
          )}
        </div>

        {/* Capture folder */}
        <div className="space-y-2">
          <p className="text-xs text-muted font-mono uppercase tracking-wider">Capture Folder</p>
          {captureFolder && (
            <p className="text-xs font-mono text-gray-400 truncate">{captureFolder}</p>
          )}
          <div className="flex gap-2">
            <Btn disabled={disabled} onClick={openFolder}>Open Folder</Btn>
            <Btn disabled={disabled} onClick={() => { setFolderDraft(captureFolder); setShowFolderInput(true); }}>
              Change Folder
            </Btn>
          </div>
          {showFolderInput && (
            <div className="flex gap-2">
              <input
                value={folderDraft}
                onChange={(e) => setFolderDraft(e.target.value)}
                placeholder="/path/to/folder"
                className="flex-1 rounded-md bg-bg border border-border px-2 py-1 text-xs focus:border-accent focus:outline-none"
              />
              <Btn onClick={applyFolder}>Set</Btn>
              <Btn onClick={() => setShowFolderInput(false)}>✕</Btn>
            </div>
          )}
        </div>

        {status && (
          <p className="text-xs text-accent border border-accent/30 bg-accent/10 rounded px-2 py-1">{status}</p>
        )}
      </div>
    </div>
  );
}

function Btn({
  onClick, disabled, children, active,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
  active?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={
        "rounded-md border px-2.5 py-1 text-xs transition disabled:opacity-40 disabled:cursor-not-allowed " +
        (active
          ? "border-accent/60 bg-accent/20 text-accent"
          : "border-border text-muted hover:border-accent/50 hover:text-gray-200")
      }
    >
      {children}
    </button>
  );
}
