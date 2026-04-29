"use client";

import { useEffect, useMemo, useState } from "react";

type DetectedOS = "win" | "macos" | "linux" | "unknown";

function detectOS(): DetectedOS {
  if (typeof navigator === "undefined") return "unknown";
  const ua = navigator.userAgent.toLowerCase();
  if (ua.includes("windows")) return "win";
  if (ua.includes("mac os") || ua.includes("macintosh")) return "macos";
  if (ua.includes("linux") || ua.includes("ubuntu") || ua.includes("debian") || ua.includes("fedora"))
    return "linux";
  return "unknown";
}

const PLATFORMS: { id: DetectedOS; label: string; ext: string }[] = [
  { id: "win", label: "Windows", ext: ".exe" },
  { id: "macos", label: "macOS", ext: ".pkg" },
  { id: "linux", label: "Linux", ext: "" },
];

export function JoinClient({ token }: { token: string }) {
  const [detected, setDetected] = useState<DetectedOS>("unknown");

  useEffect(() => {
    setDetected(detectOS());
  }, []);

  const primary = useMemo(
    () => PLATFORMS.find((p) => p.id === detected) ?? PLATFORMS[0],
    [detected],
  );

  return (
    <div className="mt-8 space-y-4">
      <a
        href={`/install/${encodeURIComponent(token)}/download/${primary.id}`}
        className="block rounded-md bg-accent text-bg font-medium text-center px-6 py-4 hover:shadow-glow transition"
      >
        Download for {primary.label}
        <span className="block text-xs font-mono uppercase tracking-wider mt-1 opacity-80">
          {primary.id}{primary.ext} · ~5 MB
        </span>
      </a>

      <details className="rounded-md border border-border bg-surface/60 px-4 py-2">
        <summary className="cursor-pointer text-sm text-muted hover:text-gray-300 transition select-none">
          Other operating systems
        </summary>
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          {PLATFORMS.filter((p) => p.id !== primary.id).map((p) => (
            <a
              key={p.id}
              href={`/install/${encodeURIComponent(token)}/download/${p.id}`}
              className="rounded-md border border-border bg-bg px-3 py-2 text-sm text-center hover:border-accent/40 hover:text-accent transition"
            >
              {p.label}
              <span className="block text-[11px] font-mono uppercase tracking-wider mt-0.5 text-muted">
                {p.id}{p.ext}
              </span>
            </a>
          ))}
        </div>
      </details>

      <p className="text-xs text-muted">
        Your browser may warn about an unsigned download. That's normal — accept and run it.
      </p>
    </div>
  );
}
