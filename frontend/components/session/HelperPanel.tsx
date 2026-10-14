"use client";

import { useEffect, useState } from "react";
import { useTechnicianChannel } from "./TechnicianChannel";

type HelperProvider = "bing" | "google";
type HelperTool = "none" | "lasso" | "cross";

export function HelperPanel({ onClose }: { onClose: () => void }) {
  const channel = useTechnicianChannel();
  const [provider, setProvider] = useState<HelperProvider>("google");
  const [tool, setTool] = useState<HelperTool>("none");
  const [clipboardHelp, setClipboardHelp] = useState(false);

  // Sync state from agent on channel open
  useEffect(() => {
    return channel.subscribe((m) => {
      if (m.type === "helper_state") {
        if (m.provider === "bing" || m.provider === "google") setProvider(m.provider);
        if (m.tool === "none" || m.tool === "lasso" || m.tool === "cross") setTool(m.tool);
        if (typeof m.clipboard_help === "boolean") setClipboardHelp(m.clipboard_help);
      }
    });
  }, [channel]);

  useEffect(() => {
    if (channel.status === "open") {
      channel.send({ type: "helper_state_get" });
    }
  }, [channel.status]); // eslint-disable-line react-hooks/exhaustive-deps

  function changeProvider(p: HelperProvider) {
    setProvider(p);
    channel.send({ type: "helper_provider_set", provider: p });
  }

  function changeTool(t: HelperTool) {
    setTool(t);
    channel.send({ type: "helper_tool_set", tool: t });
  }

  function toggleClipboardHelp() {
    const next = !clipboardHelp;
    setClipboardHelp(next);
    channel.send({ type: "helper_clipboard_set", enabled: next });
  }

  const disabled = channel.status !== "open";

  const providers: { value: HelperProvider; label: string }[] = [
    { value: "google", label: "Google" },
    { value: "bing", label: "Bing" },
  ];

  const tools: { value: HelperTool; label: string; icon: string }[] = [
    { value: "none", label: "None", icon: "✕" },
    { value: "lasso", label: "Lasso", icon: "◌" },
    { value: "cross", label: "Cross", icon: "✛" },
  ];

  return (
    <div className="rounded-lg border border-border bg-surface w-64 flex flex-col">
      <header className="flex items-center justify-between px-4 py-2.5 border-b border-border">
        <span className="text-xs font-mono uppercase tracking-wider text-muted">Helper</span>
        <button onClick={onClose} className="text-muted hover:text-gray-200 transition text-sm">✕</button>
      </header>

      <div className="p-4 space-y-4">
        {/* Provider */}
        <div className="space-y-2">
          <p className="text-xs text-muted font-mono uppercase tracking-wider">Provider</p>
          <div className="flex gap-1.5">
            {providers.map((p) => (
              <button
                key={p.value}
                onClick={() => changeProvider(p.value)}
                disabled={disabled}
                className={
                  "flex-1 rounded-md border px-2 py-1.5 text-xs transition disabled:opacity-40 " +
                  (provider === p.value
                    ? "border-accent/60 bg-accent/20 text-accent"
                    : "border-border text-muted hover:border-accent/50 hover:text-gray-200")
                }
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {/* Tool */}
        <div className="space-y-2">
          <p className="text-xs text-muted font-mono uppercase tracking-wider">Tool</p>
          <div className="flex gap-1.5">
            {tools.map((t) => (
              <button
                key={t.value}
                onClick={() => changeTool(t.value)}
                disabled={disabled}
                title={t.label}
                className={
                  "flex-1 rounded-md border px-2 py-2 text-sm transition disabled:opacity-40 " +
                  (tool === t.value
                    ? "border-accent/60 bg-accent/20 text-accent"
                    : "border-border text-muted hover:border-accent/50 hover:text-gray-200")
                }
              >
                {t.icon}
              </button>
            ))}
          </div>
          <p className="text-[10px] text-muted font-mono capitalize">{tool}</p>
        </div>

        {/* Clipboard Help */}
        <div className="border-t border-border pt-3">
          <button
            onClick={toggleClipboardHelp}
            disabled={disabled}
            className={
              "w-full flex items-center justify-between rounded-md border px-3 py-2 text-sm transition disabled:opacity-40 " +
              (clipboardHelp
                ? "border-accent/60 bg-accent/20 text-accent"
                : "border-border text-gray-300 hover:border-accent/50")
            }
          >
            <span>Enable Clipboard Help</span>
            <span
              className={
                "text-xs font-mono px-1.5 py-0.5 rounded " +
                (clipboardHelp ? "bg-accent/30 text-accent" : "bg-border/50 text-muted")
              }
            >
              {clipboardHelp ? "ON" : "OFF"}
            </span>
          </button>
        </div>
      </div>
    </div>
  );
}
