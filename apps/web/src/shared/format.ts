// No fixed time zone: the server runs on the owner's machine, so its local
// time is the owner's (set TZ in Docker).
const time = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

export function formatWhen(iso: string): string {
  return time.format(new Date(iso));
}

export function formatTokens(n: number): string {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}k`;
  return String(n);
}

/** "1 goal", "3 goals". */
export function plural(n: number, word: string): string {
  return `${String(n)} ${word}${n === 1 ? "" : "s"}`;
}

/** How long ago, short, for under a day: "now", "5m", "3h"; null after a day
 * (each caller words older times its own way). */
export function agoShort(seconds: number): string | null {
  if (seconds < 60) return "now";
  if (seconds < 3600) return `${String(Math.floor(seconds / 60))}m`;
  if (seconds < 86_400) return `${String(Math.floor(seconds / 3600))}h`;
  return null;
}

/** A date and time in the reader's locale: "3 Nov 2026, 14:05". */
export function dateTime(date: Date): string {
  return date.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}
