"use client";

import { useState } from "react";

export function GuestInviteDialog({
  sessionId,
  onClose,
}: {
  sessionId: string;
  onClose: () => void;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [expiresIn, setExpiresIn] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function generate() {
    setError(null);
    setLoading(true);
    try {
      const r = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/guest-invite`, {
        method: "POST",
        credentials: "include",
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(body?.detail ?? `HTTP ${r.status}`);
      }
      const body = await r.json();
      const fullUrl = `${location.origin}${body.url}`;
      setUrl(fullUrl);
      setExpiresIn(Number(body.expires_in));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function copy() {
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* noop */
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-lg border border-border bg-surface p-6 space-y-4">
        <header>
          <h2 className="text-lg font-semibold">Invite a guest viewer</h2>
          <p className="mt-1 text-sm text-muted">
            Generates a short-lived URL for read-only access. The invitee
            can watch the session but cannot send input or files.
          </p>
        </header>

        {url ? (
          <>
            <div className="space-y-1">
              <label className="text-xs font-mono uppercase tracking-wider text-muted">Guest URL</label>
              <div className="flex gap-2">
                <input
                  readOnly
                  value={url}
                  className="flex-1 rounded-md bg-bg border border-border px-2 py-1.5 text-xs font-mono"
                />
                <button onClick={copy} className="rounded-md border border-border px-3 py-1.5 text-sm hover:border-accent/50 hover:text-accent transition">
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
              {expiresIn ? (
                <p className="text-xs text-muted">expires in {Math.round(expiresIn / 60)} min</p>
              ) : null}
            </div>
          </>
        ) : (
          <button
            onClick={generate}
            disabled={loading}
            className="w-full rounded-md bg-accent text-bg py-2 text-sm font-medium hover:shadow-glow transition disabled:opacity-40"
          >
            {loading ? "Generating…" : "Generate invite link"}
          </button>
        )}

        {error ? (
          <p className="text-sm text-red-300 border border-danger/40 bg-danger/10 rounded px-2 py-1.5">{error}</p>
        ) : null}

        <footer className="flex justify-end">
          <button onClick={onClose} className="rounded-md border border-border px-3 py-1.5 text-sm hover:border-accent/50 hover:text-accent transition">
            Close
          </button>
        </footer>
      </div>
    </div>
  );
}
