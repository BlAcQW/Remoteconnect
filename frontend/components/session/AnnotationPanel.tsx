"use client";

import { useEffect, useRef, useState } from "react";
import { useTechnicianChannel } from "./TechnicianChannel";

type AnnotationMode = "invisible" | "view_only" | "host_draw" | "all_draw";
type DrawTool = "pen" | "line" | "rectangle" | "ellipse";
type StrokeThickness = "thin" | "medium" | "thick";

export function AnnotationPanel({ onClose }: { onClose: () => void }) {
  const channel = useTechnicianChannel();
  const [mode, setMode] = useState<AnnotationMode>("invisible");
  const [tool, setTool] = useState<DrawTool>("pen");
  const [thickness, setThickness] = useState<StrokeThickness>("medium");
  const [color, setColor] = useState("#22d3ee"); // accent cyan

  function changeMode(m: AnnotationMode) {
    setMode(m);
    channel.send({ type: "annotation_mode", mode: m });
  }

  function changeTool(t: DrawTool) {
    setTool(t);
    channel.send({ type: "annotation_tool", tool: t });
  }

  function changeThickness(t: StrokeThickness) {
    setThickness(t);
    channel.send({ type: "annotation_thickness", thickness: t });
  }

  function changeColor(c: string) {
    setColor(c);
    channel.send({ type: "annotation_color", color: c });
  }

  function clearAnnotations() {
    channel.send({ type: "annotation_clear" });
  }

  const disabled = channel.status !== "open";

  const modeOptions: { value: AnnotationMode; label: string }[] = [
    { value: "invisible", label: "Invisible" },
    { value: "view_only", label: "View Only" },
    { value: "host_draw", label: "Host Draw" },
    { value: "all_draw", label: "All Draw" },
  ];

  const toolOptions: { value: DrawTool; label: string; icon: string }[] = [
    { value: "pen", label: "Pen", icon: "✏️" },
    { value: "line", label: "Line", icon: "╱" },
    { value: "rectangle", label: "Rectangle", icon: "▭" },
    { value: "ellipse", label: "Ellipse", icon: "○" },
  ];

  const thicknessOptions: { value: StrokeThickness; label: string; px: number }[] = [
    { value: "thin", label: "Thin", px: 1 },
    { value: "medium", label: "Medium", px: 3 },
    { value: "thick", label: "Thick", px: 6 },
  ];

  const presetColors = [
    "#22d3ee", "#f43f5e", "#facc15", "#4ade80", "#a78bfa", "#fb923c", "#ffffff", "#64748b",
  ];

  return (
    <div className="rounded-lg border border-border bg-surface w-72 flex flex-col">
      <header className="flex items-center justify-between px-4 py-2.5 border-b border-border">
        <span className="text-xs font-mono uppercase tracking-wider text-muted">Annotation</span>
        <button onClick={onClose} className="text-muted hover:text-gray-200 transition text-sm">✕</button>
      </header>

      <div className="p-4 space-y-4">
        {/* Mode */}
        <div className="space-y-2">
          <p className="text-xs text-muted font-mono uppercase tracking-wider">Mode</p>
          <div className="grid grid-cols-2 gap-1.5">
            {modeOptions.map((opt) => (
              <button
                key={opt.value}
                onClick={() => changeMode(opt.value)}
                disabled={disabled}
                className={
                  "rounded-md border px-2 py-1.5 text-xs transition disabled:opacity-40 " +
                  (mode === opt.value
                    ? "border-accent/60 bg-accent/20 text-accent"
                    : "border-border text-muted hover:border-accent/50 hover:text-gray-200")
                }
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Tool */}
        <div className="space-y-2">
          <p className="text-xs text-muted font-mono uppercase tracking-wider">Tool</p>
          <div className="grid grid-cols-4 gap-1.5">
            {toolOptions.map((opt) => (
              <button
                key={opt.value}
                onClick={() => changeTool(opt.value)}
                disabled={disabled || mode === "invisible" || mode === "view_only"}
                title={opt.label}
                className={
                  "rounded-md border px-2 py-2 text-sm transition disabled:opacity-40 " +
                  (tool === opt.value
                    ? "border-accent/60 bg-accent/20 text-accent"
                    : "border-border text-muted hover:border-accent/50 hover:text-gray-200")
                }
              >
                {opt.icon}
              </button>
            ))}
          </div>
        </div>

        {/* Thickness */}
        <div className="space-y-2">
          <p className="text-xs text-muted font-mono uppercase tracking-wider">Stroke</p>
          <div className="flex gap-1.5">
            {thicknessOptions.map((opt) => (
              <button
                key={opt.value}
                onClick={() => changeThickness(opt.value)}
                disabled={disabled || mode === "invisible" || mode === "view_only"}
                title={opt.label}
                className={
                  "flex-1 rounded-md border px-2 py-2 flex items-center justify-center transition disabled:opacity-40 " +
                  (thickness === opt.value
                    ? "border-accent/60 bg-accent/20"
                    : "border-border hover:border-accent/50")
                }
              >
                <span
                  className="block rounded-full bg-gray-300"
                  style={{ height: opt.px, width: "70%" }}
                />
              </button>
            ))}
          </div>
        </div>

        {/* Color */}
        <div className="space-y-2">
          <p className="text-xs text-muted font-mono uppercase tracking-wider">Color</p>
          <div className="flex items-center gap-2 flex-wrap">
            {presetColors.map((c) => (
              <button
                key={c}
                onClick={() => changeColor(c)}
                disabled={disabled || mode === "invisible" || mode === "view_only"}
                title={c}
                className={
                  "w-6 h-6 rounded-full border-2 transition disabled:opacity-40 " +
                  (color === c ? "border-white scale-110" : "border-transparent hover:border-gray-400")
                }
                style={{ backgroundColor: c }}
              />
            ))}
            <input
              type="color"
              value={color}
              onChange={(e) => changeColor(e.target.value)}
              disabled={disabled || mode === "invisible" || mode === "view_only"}
              className="w-6 h-6 rounded cursor-pointer border border-border bg-bg disabled:opacity-40"
              title="Custom color"
            />
          </div>
        </div>

        {/* Clear */}
        <button
          onClick={clearAnnotations}
          disabled={disabled}
          className="w-full rounded-md border border-danger/50 bg-danger/10 text-red-300 hover:bg-danger/20 transition px-3 py-1.5 text-xs disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Clear All Annotations
        </button>
      </div>
    </div>
  );
}
