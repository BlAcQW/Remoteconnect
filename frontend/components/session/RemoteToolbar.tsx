"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/client-api";
import { useTechnicianChannel } from "./TechnicianChannel";

type Props = {
  sessionId: string;
  status: string;
  mouseEnabled: boolean;
  onToggleMouse: () => void;
  keyboardEnabled: boolean;
  onToggleKeyboard: () => void;
  viewOnly: boolean;
  onToggleViewOnly: () => void;
  onToggleFullscreen: () => void;
  isFullscreen: boolean;
  channelOpen: boolean;
  zoom: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onZoomReset: () => void;
  inputLocked: boolean;
  onToggleInputLock: () => void;
  screenLocked: boolean;
  onToggleScreenLock: () => void;
  onOpenHandoff: () => void;
  onOpenGuestInvite: () => void;
};

export function RemoteToolbar(props: Props) {
  const router = useRouter();
  const channel = useTechnicianChannel();
  const [ending, setEnding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ended = props.status === "ended";

  async function onEnd() {
    setError(null);
    setEnding(true);
    try {
      await api.endSession(props.sessionId);
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : (err as Error).message);
    } finally {
      setEnding(false);
    }
  }

  function sendCad() {
    channel.send({ type: "cad_send" });
  }

  return (
    <div className="pointer-events-auto flex flex-wrap items-center gap-1.5 rounded-lg border border-border bg-surface/95 backdrop-blur px-2 py-1.5 shadow-glow text-xs font-mono uppercase tracking-wider max-w-[640px]">
      <Indicator on={props.channelOpen} label={props.channelOpen ? "linked" : "offline"} />
      <Divider />

      <ToggleButton
        active={!props.viewOnly}
        onClick={props.onToggleViewOnly}
        title={props.viewOnly ? "Switch to control mode" : "Switch to view-only mode"}
        disabled={ended}
      >
        {props.viewOnly ? "View only" : "Control"}
      </ToggleButton>

      <ToggleButton active={props.mouseEnabled} onClick={props.onToggleMouse} disabled={ended || props.viewOnly} title="Mouse passthrough">
        Mouse
      </ToggleButton>
      <ToggleButton active={props.keyboardEnabled} onClick={props.onToggleKeyboard} disabled={ended || props.viewOnly} title="Keyboard passthrough">
        Kbd
      </ToggleButton>

      <Divider />

      <ToggleButton active={props.isFullscreen} onClick={props.onToggleFullscreen} title="Fullscreen">
        Full
      </ToggleButton>
      <Tiny onClick={props.onZoomOut} title="Zoom out">−</Tiny>
      <Tiny onClick={props.onZoomReset} title="Reset zoom">{Math.round(props.zoom * 100)}%</Tiny>
      <Tiny onClick={props.onZoomIn} title="Zoom in">+</Tiny>

      <Divider />

      <Tiny onClick={sendCad} disabled={!props.channelOpen} title="Send Ctrl+Alt+Del (Windows agents only, requires elevation)">
        C+A+D
      </Tiny>
      <ToggleButton active={props.screenLocked} onClick={props.onToggleScreenLock} title="Lock the remote screen with a privacy overlay" disabled={!props.channelOpen}>
        {props.screenLocked ? "Unblank" : "Blank"}
      </ToggleButton>
      <ToggleButton active={props.inputLocked} onClick={props.onToggleInputLock} title="Block agent from accepting other input" disabled={!props.channelOpen}>
        {props.inputLocked ? "Input locked" : "Lock input"}
      </ToggleButton>

      <Divider />

      <Tiny onClick={props.onOpenHandoff} disabled={ended}>Handoff</Tiny>
      <Tiny onClick={props.onOpenGuestInvite} disabled={ended}>Guest</Tiny>

      <Divider />

      <button
        onClick={onEnd}
        disabled={ended || ending}
        className="rounded-md border border-danger/50 bg-danger/10 text-red-300 hover:bg-danger/20 transition px-2.5 py-1 disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {ended ? "Ended" : ending ? "Ending…" : "End"}
      </button>
      {error ? <span className="ml-2 text-red-300 normal-case">{error}</span> : null}
    </div>
  );
}

function ToggleButton({
  active, onClick, title, disabled, children,
}: { active: boolean; onClick: () => void; title?: string; disabled?: boolean; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      title={title}
      disabled={disabled}
      className={
        "rounded-md px-2 py-1 transition disabled:opacity-40 disabled:cursor-not-allowed " +
        (active
          ? "bg-accent text-bg shadow-glow hover:brightness-110"
          : "border border-border text-muted hover:border-accent/50 hover:text-gray-200")
      }
    >
      {children}
    </button>
  );
}

function Tiny({
  onClick, title, disabled, children,
}: { onClick: () => void; title?: string; disabled?: boolean; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      title={title}
      disabled={disabled}
      className="rounded-md border border-border text-muted hover:border-accent/50 hover:text-gray-200 transition px-2 py-1 disabled:opacity-40 disabled:cursor-not-allowed"
    >
      {children}
    </button>
  );
}

function Indicator({ on, label }: { on: boolean; label: string }) {
  return (
    <span className="flex items-center gap-1.5 px-1.5">
      <span className={`inline-block w-1.5 h-1.5 rounded-full ${on ? "bg-success shadow-glow" : "bg-muted"}`} />
      <span className={on ? "text-gray-300" : "text-muted"}>{label}</span>
    </span>
  );
}

function Divider() {
  return <span className="h-4 w-px bg-border" />;
}
