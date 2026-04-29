"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";
import { api } from "@/lib/client-api";

export function LogoutButton() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  return (
    <button
      onClick={() =>
        startTransition(async () => {
          try {
            await api.logout();
          } finally {
            router.replace("/login");
            router.refresh();
          }
        })
      }
      disabled={pending}
      className="text-xs font-mono uppercase tracking-wider text-muted hover:text-accent transition disabled:opacity-50"
    >
      {pending ? "…" : "Sign out"}
    </button>
  );
}
