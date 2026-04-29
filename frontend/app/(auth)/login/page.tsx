import { Suspense } from "react";
import { LoginForm } from "@/components/LoginForm";

export const dynamic = "force-dynamic";

export default function LoginPage() {
  return (
    <main className="min-h-screen grid place-items-center p-6">
      <div className="w-full max-w-md rounded-xl border border-border bg-surface p-8 shadow-glow">
        <div className="mb-8">
          <div className="font-mono text-xs uppercase tracking-[0.2em] text-accent">RemoteConnect</div>
          <h1 className="mt-2 text-2xl font-semibold">Technician sign in</h1>
          <p className="mt-1 text-sm text-muted">
            Connect to your registered machines from one console.
          </p>
        </div>
        <Suspense>
          <LoginForm />
        </Suspense>
      </div>
    </main>
  );
}
