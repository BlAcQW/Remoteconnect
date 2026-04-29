import { JoinClient } from "@/components/JoinClient";

export const dynamic = "force-dynamic";

async function fetchInfo(token: string) {
  // Use absolute URL — server-side fetch from a Next.js route inside Docker
  // resolves /quick-invite/{token} via the configured backend.
  const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8765";
  try {
    const r = await fetch(`${backend}/quick-invite/${encodeURIComponent(token)}`, {
      cache: "no-store",
    });
    if (!r.ok) return { valid: false as const, reason: `HTTP ${r.status}` };
    return (await r.json()) as
      | { valid: true; expires_in: number; technician_email: string | null }
      | { valid: false; reason: string };
  } catch (e) {
    return { valid: false as const, reason: (e as Error).message };
  }
}

export default async function JoinPage({ params }: { params: { token: string } }) {
  const info = await fetchInfo(params.token);

  return (
    <div className="min-h-screen bg-bg flex flex-col">
      <header className="border-b border-border bg-surface/80">
        <div className="mx-auto max-w-3xl px-6 h-14 flex items-center justify-between">
          <span className="text-xs font-mono uppercase tracking-[0.2em] text-accent">
            RemoteConnect
          </span>
          <span className="text-xs font-mono uppercase tracking-wider text-muted">
            quick connect
          </span>
        </div>
      </header>

      <main className="flex-1 mx-auto w-full max-w-3xl px-6 py-12">
        {info.valid ? (
          <>
            <h1 className="text-2xl font-semibold">You've been invited to a remote support session.</h1>
            <p className="mt-3 text-muted">
              {info.technician_email ? (
                <>
                  <span className="text-gray-300">{info.technician_email}</span> wants to help you
                  with your machine.
                </>
              ) : (
                <>A technician wants to help you with your machine.</>
              )}{" "}
              Pick the installer for your operating system below, then run it.
            </p>
            <p className="mt-1 text-xs text-muted">
              Invite expires in {Math.round((info.expires_in ?? 0) / 60)} min — single use.
            </p>

            <JoinClient token={params.token} />
          </>
        ) : (
          <>
            <h1 className="text-2xl font-semibold">This invite is no longer valid.</h1>
            <p className="mt-3 text-muted">{info.reason}</p>
            <p className="mt-3 text-sm text-muted">
              Ask the technician to send you a new link.
            </p>
          </>
        )}

        <section className="mt-12 rounded-md border border-border bg-surface/40 p-5 text-sm">
          <h3 className="text-xs font-mono uppercase tracking-wider text-muted mb-2">
            What this does
          </h3>
          <ul className="space-y-1.5 text-muted list-disc pl-5">
            <li>
              Installs a small background agent under your user account
              (no administrator rights needed).
            </li>
            <li>
              Lets the technician see your screen and use your mouse and keyboard
              while the session is active.
            </li>
            <li>
              You can stop a session at any time by quitting the agent.
            </li>
            <li>
              Files transferred during the session land in a dedicated folder
              (<span className="font-mono">~/.local/share/remoteconnect-agent/agent/files/</span> on
              Linux/macOS, <span className="font-mono">%LOCALAPPDATA%\RemoteConnect\agent\files\</span>{" "}
              on Windows).
            </li>
          </ul>
        </section>
      </main>
    </div>
  );
}
