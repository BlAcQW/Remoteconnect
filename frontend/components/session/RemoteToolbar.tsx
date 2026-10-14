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
  // Tier A panel openers
  onOpenShell: () => void;
  onOpenProcesses: () => void;
  onOpenFiles: () => void;
  // Tier B panel openers
  onOpenSysInfo: () => void;
  onOpenServices: () => void;
  onOpenVitals: () => void;
  // New panel openers
  onOpenScreenCapture: () => void;
  onOpenSound: () => void;
  onOpenAnnotation: () => void;
  onOpenToolbox: () => void;
  onOpenStatus: () => void;
  onOpenLogonSession: () => void;
  // Essentials extras
  wakeLocked: boolean;
  onToggleWakeLock: () => void;
  clipboardShared: boolean;
  onToggleClipboardShare: () => void;
  printerMode: PrinterMode;
  onSetPrinterMode: (m: PrinterMode) => void;
  // More panel openers
  onOpenParticipants: () => void;
  onOpenHelper: () => void;
  onOpenChat: () => void;
};

export type PrinterMode = "none" | "default" | "all";
type PowerVerb = "reboot" | "shutdown" | "logoff";
type RebootMode = "normal" | "safe";

export function RemoteToolbar(props: Props) {
  const router = useRouter();
  const channel = useTechnicianChannel();
  const [ending, setEnding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showRebootMenu, setShowRebootMenu] = useState(false);

  const ended = props.status === "ended";
  const [showPrinterMenu, setShowPrinterMenu] = useState(false);

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

  function sendClipboardKeystrokes() {
    channel.send({ type: "clipboard_keystroke_send" });
  }

  function powerAction(verb: PowerVerb, mode: RebootMode = "normal") {
    const labels: Record<PowerVerb, string> = {
      reboot: mode === "safe" ? "Reboot to Safe Mode" : "Reboot",
      shutdown: "Shutdown",
      logoff: "Log off",
    };
    if (
      !window.confirm(
        `${labels[verb]} the remote machine in 30 seconds?\n\nThe customer will see a warning notification before it happens.`,
      )
    )
      return;
    const requestId = newRequestId();
    channel.send({
      type: "power_action",
      request_id: requestId,
      verb,
      mode,
      delay_s: 30,
      message: `RemoteConnect technician requested ${labels[verb].toLowerCase()} in 30 seconds`,
    });
    setShowRebootMenu(false);
  }

  function promptCredentials(action: "prompt_storage" | "send_screen") {
    channel.send({ type: "credentials_action", action });
  }

  return (
    <div className="pointer-events-auto flex flex-wrap items-center gap-1.5 rounded-lg border border-border bg-surface/95 backdrop-blur px-2 py-1.5 shadow-glow text-xs font-mono uppercase tracking-wider max-w-[720px]">
      <Indicator on={props.channelOpen} label={props.channelOpen ? "linked" : "offline"} />
      <Divider />

      {/* View */}
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

      {/* Zoom */}
      <ToggleButton active={props.isFullscreen} onClick={props.onToggleFullscreen} title="Fullscreen">
        Full
      </ToggleButton>
      <Tiny onClick={props.onZoomOut} title="Zoom out">−</Tiny>
      <Tiny onClick={props.onZoomReset} title="Reset zoom">{Math.round(props.zoom * 100)}%</Tiny>
      <Tiny onClick={props.onZoomIn} title="Zoom in">+</Tiny>

      <Divider />

      {/* Essentials */}
      <Tiny onClick={sendCad} disabled={!props.channelOpen} title="Send Ctrl+Alt+Del (Windows agents only, requires elevation)">
        C+A+D
      </Tiny>
      <Tiny onClick={sendClipboardKeystrokes} disabled={!props.channelOpen} title="Send clipboard contents as keystrokes to remote">
        Clip→Keys
      </Tiny>
      <ToggleButton active={props.screenLocked} onClick={props.onToggleScreenLock} title="Lock the remote screen with a privacy overlay" disabled={!props.channelOpen}>
        {props.screenLocked ? "Unblank" : "Blank"}
      </ToggleButton>
      <ToggleButton active={props.inputLocked} onClick={props.onToggleInputLock} title="Block agent from accepting other input" disabled={!props.channelOpen}>
        {props.inputLocked ? "Input locked" : "Lock input"}
      </ToggleButton>
      <ToggleButton active={props.wakeLocked} onClick={props.onToggleWakeLock} title="Prevent remote machine from sleeping" disabled={!props.channelOpen}>
        {props.wakeLocked ? "Wake locked" : "Wake lock"}
      </ToggleButton>
      <ToggleButton active={props.clipboardShared} onClick={props.onToggleClipboardShare} title="Share clipboard between host and remote" disabled={!props.channelOpen}>
        {props.clipboardShared ? "Clip shared" : "Share clip"}
      </ToggleButton>

      {/* Printers */}
      <div className="relative">
        <button
          disabled={!props.channelOpen}
          onClick={() => setShowPrinterMenu((v) => !v)}
          title="Printer sharing mode"
          className="rounded-md border border-border text-muted hover:border-accent/50 hover:text-gray-200 transition px-2 py-1 disabled:opacity-40 disabled:cursor-not-allowed text-xs font-mono uppercase tracking-wider"
        >
          {props.printerMode === "none" ? "No Printer" : props.printerMode === "default" ? "Dflt Printer" : "All Printers"} ▾
        </button>
        {showPrinterMenu && (
          <div className="absolute top-full left-0 mt-1 z-50 flex flex-col rounded-md border border-border bg-surface/95 backdrop-blur shadow-glow min-w-[10rem]">
            {(["none", "default", "all"] as PrinterMode[]).map((m) => (
              <button
                key={m}
                onClick={() => { props.onSetPrinterMode(m); setShowPrinterMenu(false); }}
                className={
                  "px-3 py-1.5 text-left text-xs transition hover:bg-white/5 " +
                  (props.printerMode === m ? "text-accent" : "text-muted hover:text-gray-200")
                }
              >
                {m === "none" ? "No Printer" : m === "default" ? "Default Printer" : "All Printers"}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Credentials */}
      <div className="relative group">
        <Tiny disabled={!props.channelOpen} onClick={() => {}} title="Manage credentials">
          Creds ▾
        </Tiny>
        <div className="absolute top-full left-0 mt-1 hidden group-hover:flex group-focus-within:flex flex-col z-50 rounded-md border border-border bg-surface/95 backdrop-blur shadow-glow min-w-[10rem]">
          <button
            onClick={() => promptCredentials("prompt_storage")}
            disabled={!props.channelOpen}
            className="px-3 py-1.5 text-left text-xs text-muted hover:text-gray-200 hover:bg-white/5 transition disabled:opacity-40"
          >
            Prompt For Storage
          </button>
          <button
            onClick={() => promptCredentials("send_screen")}
            disabled={!props.channelOpen}
            className="px-3 py-1.5 text-left text-xs text-muted hover:text-gray-200 hover:bg-white/5 transition disabled:opacity-40"
          >
            Send To Screen
          </button>
        </div>
      </div>

      <Divider />

      {/* Tools */}
      <Tiny onClick={props.onOpenShell} disabled={ended || !props.channelOpen} title="Hidden shell (cmd / powershell / bash)">
        Shell
      </Tiny>
      <Tiny onClick={props.onOpenFiles} disabled={ended || !props.channelOpen} title="File browser (browse / download / upload)">
        Files
      </Tiny>
      <Tiny onClick={props.onOpenProcesses} disabled={ended || !props.channelOpen} title="Process list + task killer">
        Procs
      </Tiny>
      <Tiny onClick={props.onOpenSysInfo} disabled={ended || !props.channelOpen} title="System info / device report">
        Info
      </Tiny>
      <Tiny onClick={props.onOpenServices} disabled={ended || !props.channelOpen} title="Services (Windows services / systemd units)">
        Svcs
      </Tiny>
      <Tiny onClick={props.onOpenVitals} disabled={ended || !props.channelOpen} title="Live CPU / memory / disk / net">
        Vitals
      </Tiny>

      <Divider />

      {/* New panels */}
      <Tiny onClick={props.onOpenScreenCapture} disabled={ended || !props.channelOpen} title="Screenshot and screen recording">
        Capture
      </Tiny>
      <Tiny onClick={props.onOpenSound} disabled={ended || !props.channelOpen} title="Audio mode and device selection">
        Sound
      </Tiny>
      <Tiny onClick={props.onOpenAnnotation} disabled={ended || !props.channelOpen} title="Annotation tools">
        Draw
      </Tiny>
      <Tiny onClick={props.onOpenToolbox} disabled={ended || !props.channelOpen} title="Deploy installer files to remote">
        Toolbox
      </Tiny>
      <Tiny onClick={props.onOpenLogonSession} disabled={ended || !props.channelOpen} title="Select logon session / share desktop">
        Session
      </Tiny>
      <Tiny onClick={props.onOpenStatus} title="Connection status and info">
        Status
      </Tiny>
      <Tiny onClick={props.onOpenParticipants} title="Connected participants">
        People
      </Tiny>
      <Tiny onClick={props.onOpenHelper} disabled={ended || !props.channelOpen} title="Helper tools (search provider, lasso, clipboard help)">
        Helper
      </Tiny>
      <Tiny onClick={props.onOpenChat} disabled={ended || !props.channelOpen} title="In-session chat with remote participants">
        Chat
      </Tiny>

      <Divider />

      {/* Power with reboot-to-safe-mode */}
      <div className="relative">
        <div className="flex">
          <Tiny
            onClick={() => powerAction("reboot")}
            disabled={ended || !props.channelOpen}
            title="Reboot the remote machine in 30s"
          >
            Reboot
          </Tiny>
          <button
            disabled={ended || !props.channelOpen}
            onClick={() => setShowRebootMenu((v) => !v)}
            title="Reboot options"
            className="rounded-r-md border border-l-0 border-border text-muted hover:border-accent/50 hover:text-gray-200 transition px-1 py-1 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            ▾
          </button>
        </div>
        {showRebootMenu && (
          <div className="absolute top-full left-0 mt-1 z-50 flex flex-col rounded-md border border-border bg-surface/95 backdrop-blur shadow-glow min-w-[10rem]">
            <button
              onClick={() => powerAction("reboot", "normal")}
              className="px-3 py-1.5 text-left text-xs text-muted hover:text-gray-200 hover:bg-white/5 transition"
            >
              To Normal Mode
            </button>
            <button
              onClick={() => powerAction("reboot", "safe")}
              className="px-3 py-1.5 text-left text-xs text-muted hover:text-gray-200 hover:bg-white/5 transition"
            >
              To Safe Mode
            </button>
          </div>
        )}
      </div>
      <Tiny onClick={() => powerAction("shutdown")} disabled={ended || !props.channelOpen} title="Shut the remote machine down in 30s">
        Shutdown
      </Tiny>
      <Tiny onClick={() => powerAction("logoff")} disabled={ended || !props.channelOpen} title="Log the customer out">
        Logoff
      </Tiny>

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

function newRequestId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}
