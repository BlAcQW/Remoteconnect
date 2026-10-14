"use client";

import { useEffect, useState } from "react";
import { useTechnicianChannel } from "./TechnicianChannel";

type ToolboxItem = { name: string; size?: string; path: string };

export function ToolboxPanel({ onClose }: { onClose: () => void }) {
  const channel = useTechnicianChannel();
  const [personalItems, setPersonalItems] = useState<ToolboxItem[]>([]);
  const [sharedItems, setSharedItems] = useState<ToolboxItem[]>([]);
  const [personalFolder, setPersonalFolder] = useState("");
  const [showFolderInput, setShowFolderInput] = useState(false);
  const [folderDraft, setFolderDraft] = useState("");
  const [deploying, setDeploying] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [tab, setTab] = useState<"personal" | "shared">("personal");

  useEffect(() => {
    return channel.subscribe((m) => {
      if (m.type === "toolbox_list") {
        if (Array.isArray(m.personal)) setPersonalItems(m.personal as ToolboxItem[]);
        if (Array.isArray(m.shared)) setSharedItems(m.shared as ToolboxItem[]);
        if (m.personal_folder) setPersonalFolder(String(m.personal_folder));
      }
      if (m.type === "toolbox_deploy_result") {
        setDeploying(null);
        if (m.ok) {
          setStatus(`Deployed: ${m.name}`);
        } else {
          setStatus(`Failed: ${m.reason ?? "unknown error"}`);
        }
        setTimeout(() => setStatus(null), 4000);
      }
    });
  }, [channel]);

  useEffect(() => {
    if (channel.status === "open") {
      channel.send({ type: "toolbox_list_get" });
    }
  }, [channel.status]); // eslint-disable-line react-hooks/exhaustive-deps

  function deploy(item: ToolboxItem) {
    setDeploying(item.path);
    channel.send({ type: "toolbox_deploy", path: item.path, name: item.name });
  }

  function openPersonalFolder() {
    channel.send({ type: "toolbox_folder_open", scope: "personal" });
  }

  function openSharedFolder() {
    channel.send({ type: "toolbox_folder_open", scope: "shared" });
  }

  function applyFolder() {
    const folder = folderDraft.trim();
    setPersonalFolder(folder);
    channel.send({ type: "toolbox_folder_set", folder });
    setShowFolderInput(false);
  }

  const disabled = channel.status !== "open";
  const items = tab === "personal" ? personalItems : sharedItems;

  return (
    <div className="rounded-lg border border-border bg-surface w-96 flex flex-col max-h-[520px]">
      <header className="flex items-center justify-between px-4 py-2.5 border-b border-border">
        <span className="text-xs font-mono uppercase tracking-wider text-muted">Toolbox</span>
        <button onClick={onClose} className="text-muted hover:text-gray-200 transition text-sm">✕</button>
      </header>

      {/* Tabs */}
      <div className="flex border-b border-border">
        {(["personal", "shared"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={
              "flex-1 px-3 py-2 text-xs font-mono uppercase tracking-wider transition " +
              (tab === t
                ? "border-b-2 border-accent text-accent"
                : "text-muted hover:text-gray-200")
            }
          >
            {t === "personal" ? "Personal" : "Shared"}
          </button>
        ))}
      </div>

      {/* Items list */}
      <div className="flex-1 overflow-y-auto">
        {items.length === 0 ? (
          <p className="px-4 py-6 text-xs text-muted italic text-center">
            No installer files found. Add .msi/.exe files to the toolbox folder.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {items.map((item) => (
              <li key={item.path} className="flex items-center justify-between px-4 py-2.5 gap-3 hover:bg-white/5 transition">
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-gray-200 truncate">{item.name}</p>
                  {item.size && (
                    <p className="text-xs text-muted font-mono">{item.size}</p>
                  )}
                </div>
                <button
                  onClick={() => deploy(item)}
                  disabled={disabled || deploying === item.path}
                  className="rounded-md border border-accent/40 text-accent hover:bg-accent/10 transition px-2.5 py-1 text-xs disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0"
                >
                  {deploying === item.path ? "Deploying…" : "Deploy"}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Folder management */}
      <div className="border-t border-border p-3 space-y-2">
        {tab === "personal" && (
          <>
            {personalFolder && (
              <p className="text-xs font-mono text-gray-400 truncate">{personalFolder}</p>
            )}
            <div className="flex gap-2">
              <button
                onClick={openPersonalFolder}
                disabled={disabled}
                className="flex-1 rounded-md border border-border text-xs text-muted px-2 py-1.5 hover:border-accent/50 hover:text-gray-200 transition disabled:opacity-40"
              >
                Open Folder
              </button>
              <button
                onClick={() => { setFolderDraft(personalFolder); setShowFolderInput(true); }}
                disabled={disabled}
                className="flex-1 rounded-md border border-border text-xs text-muted px-2 py-1.5 hover:border-accent/50 hover:text-gray-200 transition disabled:opacity-40"
              >
                Change Folder
              </button>
            </div>
            {showFolderInput && (
              <div className="flex gap-2">
                <input
                  value={folderDraft}
                  onChange={(e) => setFolderDraft(e.target.value)}
                  placeholder="/path/to/toolbox"
                  className="flex-1 rounded-md bg-bg border border-border px-2 py-1 text-xs focus:border-accent focus:outline-none"
                />
                <button onClick={applyFolder} className="rounded-md border border-accent/40 text-accent px-2 py-1 text-xs">Set</button>
                <button onClick={() => setShowFolderInput(false)} className="text-muted text-xs px-1">✕</button>
              </div>
            )}
          </>
        )}
        {tab === "shared" && (
          <button
            onClick={openSharedFolder}
            disabled={disabled}
            className="w-full rounded-md border border-border text-xs text-muted px-2 py-1.5 hover:border-accent/50 hover:text-gray-200 transition disabled:opacity-40"
          >
            Open Shared Folder
          </button>
        )}
      </div>

      {status && (
        <div className="px-4 pb-3">
          <p className="text-xs text-accent border border-accent/30 bg-accent/10 rounded px-2 py-1">{status}</p>
        </div>
      )}
    </div>
  );
}
