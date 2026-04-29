import { GuestViewer } from "@/components/session/GuestViewer";

export const dynamic = "force-dynamic";

export default function GuestPage({ params }: { params: { token: string } }) {
  return (
    <div className="min-h-screen flex flex-col bg-bg">
      <header className="border-b border-border bg-surface/80 sticky top-0 z-10">
        <div className="mx-auto max-w-7xl px-6 h-14 flex items-center justify-between">
          <span className="text-xs font-mono uppercase tracking-[0.2em] text-accent">
            RemoteConnect — guest viewer
          </span>
          <span className="text-xs font-mono uppercase tracking-wider text-muted">read-only</span>
        </div>
      </header>
      <main className="flex-1 mx-auto w-full max-w-7xl px-6 py-6">
        <GuestViewer token={params.token} />
      </main>
    </div>
  );
}
