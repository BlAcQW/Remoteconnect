"use client";

import { useEffect, useState } from "react";
import { useTechnicianChannel } from "./TechnicianChannel";

type SoundMode = "silent" | "speakers" | "host_mic" | "all_mics";

type MicDevice = { id: string; label: string };
type SpeakerDevice = { id: string; label: string };

export function SoundPanel({ onClose }: { onClose: () => void }) {
  const channel = useTechnicianChannel();
  const [mode, setMode] = useState<SoundMode>("silent");
  const [mics, setMics] = useState<MicDevice[]>([]);
  const [speakers, setSpeakers] = useState<SpeakerDevice[]>([]);
  const [selectedMic, setSelectedMic] = useState<string>("");
  const [selectedSpeaker, setSelectedSpeaker] = useState<string>("");
  const [volume, setVolume] = useState(80);

  useEffect(() => {
    return channel.subscribe((m) => {
      if (m.type === "audio_devices") {
        if (Array.isArray(m.mics)) setMics(m.mics as MicDevice[]);
        if (Array.isArray(m.speakers)) setSpeakers(m.speakers as SpeakerDevice[]);
        if (m.selected_mic) setSelectedMic(String(m.selected_mic));
        if (m.selected_speaker) setSelectedSpeaker(String(m.selected_speaker));
        if (typeof m.volume === "number") setVolume(m.volume);
        if (m.mode) setMode(m.mode as SoundMode);
      }
    });
  }, [channel]);

  // Request device list on mount
  useEffect(() => {
    if (channel.status === "open") {
      channel.send({ type: "audio_devices_get" });
    }
  }, [channel.status]); // eslint-disable-line react-hooks/exhaustive-deps

  function changeMode(m: SoundMode) {
    setMode(m);
    channel.send({ type: "audio_mode_set", mode: m });
  }

  function changeMic(id: string) {
    setSelectedMic(id);
    channel.send({ type: "audio_mic_set", device_id: id });
  }

  function changeSpeaker(id: string) {
    setSelectedSpeaker(id);
    channel.send({ type: "audio_speaker_set", device_id: id });
  }

  function changeVolume(v: number) {
    setVolume(v);
    channel.send({ type: "audio_volume_set", volume: v });
  }

  const disabled = channel.status !== "open";

  const modeOptions: { value: SoundMode; label: string }[] = [
    { value: "silent", label: "Silent" },
    { value: "speakers", label: "Speakers" },
    { value: "host_mic", label: "Host Mic" },
    { value: "all_mics", label: "All Mics" },
  ];

  return (
    <div className="rounded-lg border border-border bg-surface w-80 flex flex-col">
      <header className="flex items-center justify-between px-4 py-2.5 border-b border-border">
        <span className="text-xs font-mono uppercase tracking-wider text-muted">Sound</span>
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
                  "rounded-md border px-2.5 py-1.5 text-xs transition disabled:opacity-40 " +
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

        {/* Microphone */}
        <div className="space-y-1.5">
          <p className="text-xs text-muted font-mono uppercase tracking-wider">Microphone</p>
          <select
            value={selectedMic}
            onChange={(e) => changeMic(e.target.value)}
            disabled={disabled || mics.length === 0}
            className="w-full rounded-md bg-bg border border-border px-2 py-1.5 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-50"
          >
            {mics.length === 0 ? (
              <option value="">No mic devices detected</option>
            ) : (
              mics.map((d) => (
                <option key={d.id} value={d.id}>{d.label || d.id}</option>
              ))
            )}
          </select>
        </div>

        {/* Speakers + Volume */}
        <div className="space-y-1.5">
          <p className="text-xs text-muted font-mono uppercase tracking-wider">Speakers</p>
          <select
            value={selectedSpeaker}
            onChange={(e) => changeSpeaker(e.target.value)}
            disabled={disabled || speakers.length === 0}
            className="w-full rounded-md bg-bg border border-border px-2 py-1.5 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-50"
          >
            {speakers.length === 0 ? (
              <option value="">No speaker devices detected</option>
            ) : (
              speakers.map((d) => (
                <option key={d.id} value={d.id}>{d.label || d.id}</option>
              ))
            )}
          </select>

          <div className="flex items-center gap-3 pt-1">
            <span className="text-xs text-muted w-12">Volume</span>
            <input
              type="range"
              min={0}
              max={100}
              value={volume}
              onChange={(e) => changeVolume(parseInt(e.target.value, 10))}
              disabled={disabled}
              className="flex-1 accent-cyan-400"
            />
            <span className="text-xs font-mono text-gray-400 w-8 text-right">{volume}%</span>
          </div>
        </div>
      </div>
    </div>
  );
}
