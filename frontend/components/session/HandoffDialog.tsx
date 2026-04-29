"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export function HandoffDialog({
  sessionId,
  onClose,
}: {
  sessionId: string;
  onClose: () => void;
}) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const r = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/handoff`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ to_email: email.trim() }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(body?.detail ?? `HTTP ${r.status}`);
      }
      onClose();
      router.refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <form onSubmit={submit} className="w-full max-w-md rounded-lg border border-border bg-surface p-6 space-y-4">
        <header>
          <h2 className="text-lg font-semibold">Hand off session</h2>
          <p className="mt-1 text-sm text-muted">
            Transfer ownership of this session to another technician (must already
            have a RemoteConnect account).
          </p>
        </header>

        <div className="space-y-1">
          <label className="text-xs font-mono uppercase tracking-wider text-muted">Technician email</label>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-md bg-bg border border-border px-3 py-2 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </div>

        {error ? (
          <p className="text-sm text-red-300 border border-danger/40 bg-danger/10 rounded px-2 py-1.5">{error}</p>
        ) : null}

        <footer className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-md border border-border px-3 py-1.5 text-sm hover:border-accent/50 hover:text-accent transition">
            Cancel
          </button>
          <button
            type="submit"
            disabled={submitting || !email.trim()}
            className="rounded-md bg-accent text-bg px-3 py-1.5 text-sm font-medium hover:shadow-glow transition disabled:opacity-40"
          >
            {submitting ? "Handing off…" : "Hand off"}
          </button>
        </footer>
      </form>
    </div>
  );
}
