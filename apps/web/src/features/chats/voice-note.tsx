"use client";

import { useRef, useState } from "react";
import { cn } from "@/shared/ui/cn";

const BARS = [
  4, 9, 6, 12, 8, 14, 7, 10, 5, 12, 9, 6, 11, 7, 13, 8, 5, 10, 6, 9,
];

export function VoiceNote({
  src,
  duration,
  transcript,
}: {
  src: string | null;
  duration: number | null;
  transcript: string | null;
}) {
  const audio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  return (
    <div className="flex max-w-[85%] flex-col items-end gap-1">
      <div className="flex items-center gap-3 rounded-3xl rounded-br-lg bg-accent px-3 py-2 text-accent-ink">
        <button
          type="button"
          disabled={!src}
          aria-label={playing ? "Pause" : "Play voice note"}
          onClick={() => {
            const el = audio.current;
            if (!el) return;
            if (el.paused) void el.play();
            else el.pause();
          }}
          className="flex size-8 items-center justify-center rounded-full bg-accent-ink/15 hover:bg-accent-ink/25"
        >
          {playing ? (
            <svg
              viewBox="0 0 16 16"
              className="size-3.5"
              fill="currentColor"
              aria-hidden
            >
              <rect x="3.5" y="3" width="3" height="10" rx="1" />
              <rect x="9.5" y="3" width="3" height="10" rx="1" />
            </svg>
          ) : (
            <svg
              viewBox="0 0 16 16"
              className="ml-0.5 size-3.5"
              fill="currentColor"
              aria-hidden
            >
              <path d="M4 2.8v10.4a.8.8 0 0 0 1.2.7l8.4-5.2a.8.8 0 0 0 0-1.4L5.2 2.1A.8.8 0 0 0 4 2.8Z" />
            </svg>
          )}
        </button>
        <span className="flex h-6 items-center gap-[3px]" aria-hidden>
          {BARS.map((h, i) => (
            <span
              key={i}
              className={cn(
                "w-[3px] rounded-full",
                i / BARS.length < progress
                  ? "bg-accent-ink"
                  : "bg-accent-ink/40",
              )}
              style={{ height: `${String(h + 4)}px` }}
            />
          ))}
        </span>
        <span className="min-w-8 text-xs tabular-nums opacity-80">
          {formatDuration(duration)}
        </span>
        {src && (
          <audio
            ref={audio}
            src={src}
            preload="none"
            onPlay={() => {
              setPlaying(true);
            }}
            onPause={() => {
              setPlaying(false);
            }}
            onEnded={() => {
              setPlaying(false);
              setProgress(0);
            }}
            onTimeUpdate={(e) => {
              const el = e.currentTarget;
              const total = Number.isFinite(el.duration)
                ? el.duration
                : (duration ?? 0);
              setProgress(total ? el.currentTime / total : 0);
            }}
          />
        )}
      </div>
      {transcript && (
        <p className="max-w-80 text-right text-xs text-ink-3 italic">
          “{transcript}”
        </p>
      )}
    </div>
  );
}

function formatDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return "0:00";
  const s = Math.max(0, Math.round(seconds));
  return `${String(Math.floor(s / 60))}:${String(s % 60).padStart(2, "0")}`;
}
