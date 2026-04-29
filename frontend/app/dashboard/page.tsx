import { backendJson, BackendError } from "@/lib/server-api";
import type { Machine } from "@/lib/types";
import { MachineList } from "@/components/MachineList";
import { QuickConnectButton } from "@/components/QuickConnectButton";
import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  let initial: Machine[] = [];
  try {
    initial = await backendJson<Machine[]>("/machines/");
  } catch (e) {
    if (e instanceof BackendError && e.status === 401) {
      redirect("/login");
    }
    // For any other error we still render — the client SWR will surface it.
  }

  return (
    <section className="space-y-6">
      <header className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Machines</h1>
          <p className="mt-1 text-sm text-muted">
            Polling every 10s. Click <span className="text-accent">Connect</span> on a machine to
            start a session — or share a Quick Connect link with a customer to onboard a new
            machine in seconds.
          </p>
        </div>
        <QuickConnectButton />
      </header>
      <MachineList initial={initial} />
    </section>
  );
}
