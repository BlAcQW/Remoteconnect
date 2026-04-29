import Link from "next/link";
import { LogoutButton } from "@/components/LogoutButton";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-border bg-surface/80 backdrop-blur supports-[backdrop-filter]:bg-surface/60 sticky top-0 z-10">
        <div className="mx-auto max-w-7xl px-6 h-14 flex items-center justify-between">
          <Link href="/dashboard" className="flex items-center gap-3">
            <span className="inline-block w-2 h-2 rounded-full bg-accent shadow-glow" />
            <span className="font-mono text-sm tracking-[0.2em] uppercase">RemoteConnect</span>
          </Link>
          <nav className="flex items-center gap-6 text-sm">
            <Link href="/dashboard" className="text-gray-300 hover:text-accent transition">
              Machines
            </Link>
            <Link
              href="/dashboard/sessions"
              className="text-gray-300 hover:text-accent transition"
            >
              Sessions
            </Link>
            <LogoutButton />
          </nav>
        </div>
      </header>
      <main className="flex-1 mx-auto w-full max-w-7xl px-6 py-8">{children}</main>
    </div>
  );
}
