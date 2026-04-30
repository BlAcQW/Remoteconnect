"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Session } from "@/lib/types";
import { mapKey, mouseButton } from "@/lib/keymap";
import { RemoteToolbar } from "./RemoteToolbar";
import { useTechnicianChannel } from "./TechnicianChannel";
import { HandoffDialog } from "./HandoffDialog";
import { GuestInviteDialog } from "./GuestInviteDialog";

type Props = {
  session: Session;
};

const ZOOM_STEP = 0.1;
const ZOOM_MIN = 0.5;
const ZOOM_MAX = 3;

const MOUSE_MOVE_THROTTLE_MS = 25; // ~40 Hz — comfortable for cursor work
const FRAME_STALE_MS = 4000; // show "Waiting…" if no frame for this long

export function SessionViewer({ session }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const lastFrameAtRef = useRef<number>(0);
  const lastMoveAtRef = useRef(0);

  const channel = useTechnicianChannel();
  const channelOpen = channel.status === "open";

  const [mouseEnabled, setMouseEnabled] = useState(true);
  const [keyboardEnabled, setKeyboardEnabled] = useState(false);
  const [viewOnly, setViewOnly] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [hasFrame, setHasFrame] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [inputLocked, setInputLocked] = useState(false);
  const [screenLocked, setScreenLocked] = useState(false);
  const [showHandoff, setShowHandoff] = useState(false);
  const [showGuestInvite, setShowGuestInvite] = useState(false);
  const [peerCount, setPeerCount] = useState(1);
  const [idleClosed, setIdleClosed] = useState(false);

  const sessionEnded = session.status === "ended";

  const sendInput = channel.send;

  // Listen for backend events that affect viewer state
  useEffect(() => {
    return channel.subscribe((m) => {
      if (m.type === "peers" && typeof m.count === "number") {
        setPeerCount(m.count);
      } else if (m.type === "session_idle") {
        setIdleClosed(true);
      } else if (m.type === "session_handoff") {
        // Soft notice — page refresh will pick up new technician_id
      }
    });
  }, [channel]);

  function toggleViewOnly() {
    setViewOnly((v) => {
      const next = !v;
      if (next) {
        setMouseEnabled(false);
        setKeyboardEnabled(false);
      } else {
        setMouseEnabled(true);
      }
      return next;
    });
  }
  function toggleScreenLock() {
    setScreenLocked((v) => {
      const next = !v;
      channel.send({ type: next ? "lock_screen" : "unlock_screen" });
      return next;
    });
  }
  function toggleInputLock() {
    setInputLocked((v) => {
      const next = !v;
      channel.send({ type: next ? "input_lock" : "input_unlock" });
      return next;
    });
  }

  // ── Render incoming MJPEG frames from the agent over the WS ─────────────
  useEffect(() => {
    if (sessionEnded) return;
    return channel.subscribeBinary(async (data) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      try {
        const blob = new Blob([data], { type: "image/jpeg" });
        const bitmap = await createImageBitmap(blob);
        if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
          canvas.width = bitmap.width;
          canvas.height = bitmap.height;
        }
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        ctx.drawImage(bitmap, 0, 0);
        bitmap.close();
        lastFrameAtRef.current = performance.now();
        setHasFrame(true);
      } catch (err) {
        console.warn("frame decode failed", err);
      }
    });
  }, [channel, sessionEnded]);

  // Re-evaluate "stale" state every second so the overlay shows up if the
  // stream stops without a clean session end (network blip, agent paused).
  useEffect(() => {
    if (sessionEnded) return;
    const id = window.setInterval(() => {
      if (!lastFrameAtRef.current) return;
      if (performance.now() - lastFrameAtRef.current > FRAME_STALE_MS) {
        setHasFrame(false);
      }
    }, 1000);
    return () => window.clearInterval(id);
  }, [sessionEnded]);

  // ── Fullscreen ──────────────────────────────────────────────────────────
  useEffect(() => {
    function onFullscreenChange() {
      setIsFullscreen(document.fullscreenElement === containerRef.current);
    }
    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", onFullscreenChange);
  }, []);
  const onToggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {});
    } else {
      containerRef.current?.requestFullscreen().catch(() => {});
    }
  }, []);

  // ── Capture mouse on the surface ────────────────────────────────────────
  const surfaceRef = useRef<HTMLDivElement | null>(null);
  function normalizedFromEvent(e: { clientX: number; clientY: number }) {
    const el = surfaceRef.current;
    if (!el) return null;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return null;
    const nx = (e.clientX - rect.left) / rect.width;
    const ny = (e.clientY - rect.top) / rect.height;
    return { nx: clamp01(nx), ny: clamp01(ny) };
  }

  function onMouseMove(e: React.MouseEvent) {
    if (!mouseEnabled || viewOnly) return;
    const now = performance.now();
    if (now - lastMoveAtRef.current < MOUSE_MOVE_THROTTLE_MS) return;
    lastMoveAtRef.current = now;
    const norm = normalizedFromEvent(e);
    if (!norm) return;
    sendInput({ type: "mouse_move", ...norm });
  }
  function onMouseDown(e: React.MouseEvent) {
    if (!mouseEnabled || viewOnly) return;
    const norm = normalizedFromEvent(e);
    if (!norm) return;
    sendInput({ type: "mouse_click", ...norm, button: mouseButton(e.button), count: 1 });
  }
  function onWheel(e: React.WheelEvent) {
    if (!mouseEnabled || viewOnly) return;
    const norm = normalizedFromEvent(e);
    if (!norm) return;
    const dy = -Math.sign(e.deltaY) * Math.min(5, Math.ceil(Math.abs(e.deltaY) / 50));
    const dx = Math.sign(e.deltaX) * Math.min(5, Math.ceil(Math.abs(e.deltaX) / 50));
    if (dx === 0 && dy === 0) return;
    sendInput({ type: "mouse_scroll", ...norm, dx, dy });
  }

  useEffect(() => {
    if (!keyboardEnabled || sessionEnded || viewOnly) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.metaKey && (e.key === "r" || e.key === "R")) return;
      const key = mapKey(e.key);
      if (!key) return;
      e.preventDefault();
      sendInput({ type: "key_press", key });
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [keyboardEnabled, sendInput, sessionEnded, viewOnly]);

  // ── Render ──────────────────────────────────────────────────────────────
  const overlayMessage = useMemo(() => {
    if (sessionEnded) return "Session ended.";
    if (!channelOpen) return "Connecting to session…";
    if (!hasFrame) return "Waiting for the agent to publish its screen…";
    return null;
  }, [channelOpen, hasFrame, sessionEnded]);

  return (
    <div ref={containerRef} className="relative bg-black rounded-lg border border-border overflow-hidden">
      <div
        ref={surfaceRef}
        className={
          "relative aspect-video w-full select-none overflow-hidden " +
          (mouseEnabled && !sessionEnded && !viewOnly ? "cursor-crosshair" : "cursor-default")
        }
        onMouseMove={onMouseMove}
        onMouseDown={onMouseDown}
        onWheel={onWheel}
        onContextMenu={(e) => {
          if (mouseEnabled && !viewOnly) e.preventDefault();
        }}
      >
        <canvas
          ref={canvasRef}
          style={{ transform: `scale(${zoom})`, transformOrigin: "center center" }}
          className="absolute inset-0 w-full h-full object-contain bg-black transition-transform"
        />
        {overlayMessage || idleClosed ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="rounded-md border border-border bg-surface/80 backdrop-blur px-4 py-3 text-sm text-muted">
              {idleClosed ? "Session idle — channel closed. Refresh to reconnect." : overlayMessage}
            </div>
          </div>
        ) : null}
      </div>

      <div className="absolute top-3 right-3 z-10">
        <RemoteToolbar
          sessionId={session.id}
          status={session.status}
          mouseEnabled={mouseEnabled}
          onToggleMouse={() => setMouseEnabled((v) => !v)}
          keyboardEnabled={keyboardEnabled}
          onToggleKeyboard={() => setKeyboardEnabled((v) => !v)}
          viewOnly={viewOnly}
          onToggleViewOnly={toggleViewOnly}
          onToggleFullscreen={onToggleFullscreen}
          isFullscreen={isFullscreen}
          channelOpen={channelOpen}
          zoom={zoom}
          onZoomIn={() => setZoom((z) => Math.min(ZOOM_MAX, +(z + ZOOM_STEP).toFixed(2)))}
          onZoomOut={() => setZoom((z) => Math.max(ZOOM_MIN, +(z - ZOOM_STEP).toFixed(2)))}
          onZoomReset={() => setZoom(1)}
          inputLocked={inputLocked}
          onToggleInputLock={toggleInputLock}
          screenLocked={screenLocked}
          onToggleScreenLock={toggleScreenLock}
          onOpenHandoff={() => setShowHandoff(true)}
          onOpenGuestInvite={() => setShowGuestInvite(true)}
        />
      </div>

      {peerCount > 1 ? (
        <div className="absolute top-3 left-3 z-10 rounded-md border border-border bg-surface/95 backdrop-blur px-2 py-1 text-xs font-mono uppercase tracking-wider text-accent">
          {peerCount} techs in session
        </div>
      ) : null}

      {showHandoff ? (
        <HandoffDialog sessionId={session.id} onClose={() => setShowHandoff(false)} />
      ) : null}
      {showGuestInvite ? (
        <GuestInviteDialog sessionId={session.id} onClose={() => setShowGuestInvite(false)} />
      ) : null}
    </div>
  );
}

function clamp01(v: number): number {
  if (Number.isNaN(v)) return 0;
  if (v < 0) return 0;
  if (v > 1) return 1;
  return v;
}
