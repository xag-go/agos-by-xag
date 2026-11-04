import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { DraftFile } from "./composer-types";
import { toBase64 } from "@/shared/files";

export function formatSeconds(s: number): string {
  return `${String(Math.floor(s / 60))}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

function noSubscribe(): () => void {
  return () => {};
}

/** Records a voice note in the page; Hermes turns it into text on send. */
export function useVoiceNote({
  onDone,
  onError,
  maxBytes,
  maxSeconds,
}: {
  onDone: (file: DraftFile) => void;
  onError: (message: string | null) => void;
  /** The core's limit for one file (null: not known here; the core checks). */
  maxBytes: number | null;
  /** The core's longest voice note (null: not known here; the core checks). */
  maxSeconds: number | null;
}) {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [level, setLevel] = useState(0);
  const media = useRef<MediaRecorder | null>(null);
  const cancelled = useRef(false);
  const cleanup = useRef<() => void>(() => {});

  const supported = useSyncExternalStore(
    noSubscribe,
    () => "MediaRecorder" in window && "mediaDevices" in navigator,
    () => false,
  );

  useEffect(
    () => () => {
      cleanup.current();
    },
    [],
  );

  async function start() {
    onError(null);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      onError(
        "The microphone is blocked. Allow it for this site in the browser.",
      );
      return;
    }
    const type = [
      "audio/webm;codecs=opus",
      "audio/ogg;codecs=opus",
      "audio/mp4",
    ].find((t) => MediaRecorder.isTypeSupported(t));
    const rec = new MediaRecorder(
      stream,
      type ? { mimeType: type } : undefined,
    );
    const chunks: Blob[] = [];
    const began = Date.now();
    cancelled.current = false;

    const audioCtx = new AudioContext();
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;
    audioCtx.createMediaStreamSource(stream).connect(analyser);
    const samples = new Uint8Array(analyser.frequencyBinCount);
    let frame = 0;
    const tick = () => {
      analyser.getByteFrequencyData(samples);
      const avg = samples.reduce((a, b) => a + b, 0) / samples.length / 255;
      setLevel(Math.min(1, avg * 2.5));
      const elapsed = (Date.now() - began) / 1000;
      setSeconds(elapsed);
      if (maxSeconds !== null && elapsed >= maxSeconds) rec.stop();
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);

    cleanup.current = () => {
      cancelAnimationFrame(frame);
      stream.getTracks().forEach((t) => {
        t.stop();
      });
      void audioCtx.close();
    };
    rec.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.push(e.data);
    };
    rec.onstop = () => {
      cleanup.current();
      cleanup.current = () => {};
      setRecording(false);
      setLevel(0);
      if (cancelled.current) return;
      const duration = (Date.now() - began) / 1000;
      if (duration < 0.6) return;
      const mime = (rec.mimeType || "audio/webm").split(";")[0] ?? "audio/webm";
      const blob = new Blob(chunks, { type: mime });
      if (maxBytes !== null && blob.size > maxBytes) {
        onError("That voice note is too long.");
        return;
      }
      const ext = mime.includes("mp4")
        ? "m4a"
        : mime.includes("ogg")
          ? "ogg"
          : "webm";
      void toBase64(blob).then((data) => {
        onDone({
          key: `voice-${String(began)}`,
          kind: "audio",
          name: `voice-note.${ext}`,
          mime,
          size: blob.size,
          data,
          preview: URL.createObjectURL(blob),
          duration: Math.round(duration * 10) / 10,
        });
      });
    };
    media.current = rec;
    rec.start(250);
    setSeconds(0);
    setRecording(true);
  }

  return {
    supported,
    recording,
    seconds,
    level,
    start: () => {
      void start();
    },
    finish: () => {
      media.current?.stop();
    },
    cancel: () => {
      cancelled.current = true;
      media.current?.stop();
    },
  };
}
