import { scheduleHint } from "@agos/core/cron";

export const weekdays = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
];

export const hourIntervals = [1, 2, 3, 4, 6, 8, 12];

/** The schedule as the form edits it; always convertible to one cron string. */
export type Schedule =
  | { kind: "daily"; time: string }
  | { kind: "weekdays"; time: string }
  | { kind: "weekly"; time: string; day: number }
  | { kind: "monthly"; time: string; date: number }
  | { kind: "hours"; every: number; minute: number }
  | { kind: "custom"; cron: string };

function splitTime(time: string): [number, number] {
  const [h, m] = time.split(":").map(Number);
  return [h ?? 0, m ?? 0];
}

const pad = (n: number) => String(n).padStart(2, "0");

export function toCron(s: Schedule): string {
  switch (s.kind) {
    case "daily": {
      const [h, m] = splitTime(s.time);
      return `${m} ${h} * * *`;
    }
    case "weekdays": {
      const [h, m] = splitTime(s.time);
      return `${m} ${h} * * 1-5`;
    }
    case "weekly": {
      const [h, m] = splitTime(s.time);
      return `${m} ${h} * * ${s.day}`;
    }
    case "monthly": {
      const [h, m] = splitTime(s.time);
      return `${m} ${h} ${s.date} * *`;
    }
    case "hours":
      return s.every === 1
        ? `${s.minute} * * * *`
        : `${s.minute} */${s.every} * * *`;
    case "custom":
      return s.cron.trim();
  }
}

const num = (v: string) => (/^\d{1,2}$/.test(v) ? Number(v) : null);

/** Reads a cron string back into the friendliest form that produces it. */
export function fromCron(cron: string): Schedule {
  const parts = cron.trim().split(/\s+/);
  const [mi, ho, dom, mon, dow] = parts;
  if (parts.length === 5 && mi && ho && dom && mon === "*" && dow) {
    const m = num(mi);
    const h = num(ho);
    if (m !== null && h !== null) {
      const time = `${pad(h)}:${pad(m)}`;
      if (dom === "*" && dow === "*") return { kind: "daily", time };
      if (dom === "*" && dow === "1-5") return { kind: "weekdays", time };
      const d = num(dow);
      if (dom === "*" && d !== null && d <= 6)
        return { kind: "weekly", time, day: d };
      const date = num(dom);
      if (date !== null && dow === "*" && date <= 28)
        return { kind: "monthly", time, date };
    }
    if (m !== null && dom === "*" && dow === "*") {
      if (ho === "*") return { kind: "hours", every: 1, minute: m };
      const every = ho.startsWith("*/") ? num(ho.slice(2)) : null;
      if (every !== null && hourIntervals.includes(every)) {
        return { kind: "hours", every, minute: m };
      }
    }
  }
  return { kind: "custom", cron };
}

/** "Every day at 08:00", "Mondays at 09:00"… For anything else, Hermes's own
 * words for it (its job's schedule_display) when known, else the text itself. */
export function describeCron(cron: string, hermes?: string | null): string {
  if (scheduleHint(cron)) return "Invalid schedule";
  const s = fromCron(cron);
  switch (s.kind) {
    case "daily":
      return `Every day at ${s.time}`;
    case "weekdays":
      return `Weekdays at ${s.time}`;
    case "weekly":
      return `${weekdays[s.day] ?? "?"}s at ${s.time}`;
    case "monthly":
      return `Day ${s.date} of every month at ${s.time}`;
    case "hours":
      return s.every === 1
        ? `Every hour at :${pad(s.minute)}`
        : `Every ${s.every} hours at :${pad(s.minute)}`;
    case "custom":
      return hermes?.trim() || s.cron;
  }
}
