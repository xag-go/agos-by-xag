"use client";

import { useSyncExternalStore } from "react";
import { agoShort } from "./format";

// One shared minute clock for every "5m ago" label on the page.
let now = Date.now();
const listeners = new Set<() => void>();
let timer: ReturnType<typeof setInterval> | undefined;

function subscribe(listener: () => void) {
  listeners.add(listener);
  timer ??= setInterval(() => {
    now = Date.now();
    for (const l of listeners) l();
  }, 60_000);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && timer) {
      clearInterval(timer);
      timer = undefined;
    }
  };
}

/** When a chat was last active, short: "now", "5m", "3h", "Tue", "12 Sep". */
export function ago(iso: string, at: number): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, (at - t) / 1000);
  const short = agoShort(s);
  if (short) return short;
  const d = new Date(t);
  if (s < 6 * 86_400) return d.toLocaleDateString("en", { weekday: "short" });
  return d.toLocaleDateString("en", { day: "numeric", month: "short" });
}

export function TimeAgo({ iso }: { iso: string }) {
  // The server renders nothing (no clock there); the browser fills it in.
  const at = useSyncExternalStore(
    subscribe,
    () => now,
    () => 0,
  );
  if (!at) return null;
  return (
    <time dateTime={iso} title={new Date(iso).toLocaleString()}>
      {ago(iso, at)}
    </time>
  );
}
