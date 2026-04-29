"use client";

import { useState } from "react";
import { useTechnicianChannel } from "./TechnicianChannel";

export function QualityControls() {
  const channel = useTechnicianChannel();
  const [fps, setFps] = useState(15);
  const [quality, setQuality] = useState<"high" | "medium" | "low" | "grayscale">("high");

  function pushFps(v: number) {
    setFps(v);
    channel.send({ type: "fps_change", fps: v });
  }
  function pushQuality(q: typeof quality) {
    setQuality(q);
    channel.send({ type: "quality_change", quality: q });
  }

  return (
    <section className="rounded-lg border border-border bg-surface p-4 space-y-3 text-sm">
      <header className="text-xs font-mono uppercase tracking-wider text-muted">Stream quality</header>

      <div className="space-y-1">
        <label className="flex items-center justify-between text-xs">
          <span className="text-muted">FPS</span>
          <span className="font-mono">{fps}</span>
        </label>
        <input
          type="range" min={1} max={30} value={fps}
          onChange={(e) => pushFps(parseInt(e.target.value, 10))}
          disabled={channel.status !== "open"}
          className="w-full accent-cyan-400"
        />
      </div>

      <div className="space-y-1">
        <label className="text-xs text-muted">Color depth / size</label>
        <select
          value={quality}
          onChange={(e) => pushQuality(e.target.value as typeof quality)}
          disabled={channel.status !== "open"}
          className="w-full rounded-md bg-bg border border-border px-2 py-1 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-50"
        >
          <option value="high">High (1280×720, full color)</option>
          <option value="medium">Medium (960×540)</option>
          <option value="low">Low (640×360)</option>
          <option value="grayscale">Grayscale (low bandwidth)</option>
        </select>
      </div>
    </section>
  );
}
