import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { backendJson, BackendError } from "@/lib/server-api";
import type { Me, Session } from "@/lib/types";
import { SessionViewer } from "@/components/session/SessionViewer";
import { FilePanel } from "@/components/session/FilePanel";
import { ChatPanel } from "@/components/session/ChatPanel";
import { ClipboardPanel } from "@/components/session/ClipboardPanel";
import { QualityControls } from "@/components/session/QualityControls";
import { MonitorSelect } from "@/components/session/MonitorSelect";
import { TechnicianChannelProvider } from "@/components/session/TechnicianChannel";

export const dynamic = "force-dynamic";

export default async function SessionPage({ params }: { params: { id: string } }) {
  let session: Session | null = null;
  let me: Me | null = null;
  try {
    const [sessions, currentUser] = await Promise.all([
      backendJson<Session[]>("/sessions/"),
      backendJson<Me>("/auth/me"),
    ]);
    session = sessions.find((s) => s.id === params.id) ?? null;
    me = currentUser;
  } catch (e) {
    if (e instanceof BackendError && e.status === 401) {
      redirect("/login");
    }
    throw e;
  }
  if (!session) notFound();

  const sessionEnded = session.status === "ended";

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-border bg-surface/80 sticky top-0 z-10">
        <div className="mx-auto max-w-7xl px-6 h-14 flex items-center justify-between">
          <Link
            href="/dashboard"
            className="text-xs font-mono uppercase tracking-wider text-muted hover:text-accent transition"
          >
            ← Back to machines
          </Link>
          <div className="flex items-center gap-3 text-xs font-mono uppercase tracking-wider">
            <span className="text-muted">Session</span>
            <span className="text-gray-300" title={session.id}>
              {session.id.slice(0, 8)}…
            </span>
            <span className="text-muted">·</span>
            <span
              className={
                sessionEnded
                  ? "text-muted"
                  : session.status === "active"
                  ? "text-success"
                  : session.status === "consent_required"
                  ? "text-yellow-300"
                  : "text-accent"
              }
            >
              {session.status}
            </span>
          </div>
        </div>
      </header>

      <main className="flex-1 mx-auto w-full max-w-7xl px-6 py-6 space-y-4">
        <TechnicianChannelProvider sessionId={session.id} enabled={!sessionEnded}>
          <SessionViewer session={session} />

          <div className="grid gap-4 lg:grid-cols-3">
            <div className="lg:col-span-2 space-y-4">
              <FilePanel sessionEnded={sessionEnded} />
              <ChatPanel selfEmail={me?.email ?? ""} />
            </div>
            <div className="space-y-4">
              <MonitorSelect />
              <QualityControls />
              <ClipboardPanel />
            </div>
          </div>
        </TechnicianChannelProvider>

        <details className="group rounded-lg border border-border bg-surface">
          <summary className="cursor-pointer px-4 py-2.5 text-xs font-mono uppercase tracking-wider text-muted hover:text-gray-300 transition select-none">
            Session details
          </summary>
          <dl className="grid gap-4 sm:grid-cols-2 px-4 pb-4 text-sm">
            <div>
              <dt className="text-xs font-mono uppercase tracking-wider text-muted">Machine</dt>
              <dd className="mt-1 font-mono text-gray-300 break-all">{session.machine_id}</dd>
            </div>
            <div>
              <dt className="text-xs font-mono uppercase tracking-wider text-muted">Daily room</dt>
              <dd className="mt-1 font-mono text-gray-300 break-all">
                {session.daily_room_url ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs font-mono uppercase tracking-wider text-muted">Created</dt>
              <dd className="mt-1">{new Date(session.created_at).toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-xs font-mono uppercase tracking-wider text-muted">Ended</dt>
              <dd className="mt-1">
                {session.ended_at ? new Date(session.ended_at).toLocaleString() : "—"}
              </dd>
            </div>
          </dl>
        </details>
      </main>
    </div>
  );
}
