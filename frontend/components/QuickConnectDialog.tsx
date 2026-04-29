"use client";

import { useEffect, useState } from "react";

type Invite = { token: string; url: string; expires_at: string; expires_in: number };

export function QuickConnectDialog({ onClose }: { onClose: () => void }) {
  const [invite, setInvite] = useState<Invite | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const r = await fetch("/api/quick-invite", {
          method: "POST",
          credentials: "include",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({}),
        });
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          throw new Error(body?.detail ?? `HTTP ${r.status}`);
        }
        const data = (await r.json()) as Invite;
        if (!cancelled) setInvite(data);
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function copy() {
    if (!invite) return;
    try {
      await navigator.clipboard.writeText(invite.url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard unavailable */
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg rounded-lg border border-border bg-surface p-6 space-y-4">
        <header>
          <h2 className="text-lg font-semibold">Quick Connect — invite a customer</h2>
          <p className="mt-1 text-sm text-muted">
            Share this URL with the customer. They click it, download the
            installer for their OS, and run it. Within a minute their machine
            appears in your dashboard with a session ready.
          </p>
        </header>

        {loading ? <p className="text-sm text-muted">Generating invite…</p> : null}

        {invite ? (
          <>
            <div className="space-y-1">
              <label className="text-xs font-mono uppercase tracking-wider text-muted">Share URL</label>
              <div className="flex gap-2">
                <input
                  readOnly
                  value={invite.url}
                  onFocus={(e) => e.currentTarget.select()}
                  className="flex-1 rounded-md bg-bg border border-border px-2 py-1.5 text-xs font-mono"
                />
                <button
                  onClick={copy}
                  className="rounded-md border border-border px-3 py-1.5 text-sm hover:border-accent/50 hover:text-accent transition"
                >
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
              <p className="text-xs text-muted">
                expires in {Math.round(invite.expires_in / 60)} min · single use
              </p>
            </div>

            <div className="rounded-md border border-border bg-bg p-3 text-xs text-muted">
              <p className="text-gray-300 mb-1 font-medium">What the customer sees</p>
              <p>1. Lands on a page that auto-detects their OS</p>
              <p>2. Clicks "Download for Windows / macOS / Linux"</p>
              <p>3. Runs the installer (no admin rights needed)</p>
              <p>4. Session pre-creates here automatically — click their card to join</p>
            </div>
          </>
        ) : null}

        {error ? (
          <p className="text-sm text-red-300 border border-danger/40 bg-danger/10 rounded px-2 py-1.5">
            {error}
          </p>
        ) : null}

        <footer className="flex justify-end">
          <button
            onClick={onClose}
            className="rounded-md border border-border px-3 py-1.5 text-sm hover:border-accent/50 hover:text-accent transition"
          >
            Close
          </button>
        </footer>
      </div>
    </div>
  );
}
