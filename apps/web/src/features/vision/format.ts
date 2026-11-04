import type { PlanNode } from "@/data/types";

/** A number to read: grouped digits (10,000), at most two decimals. */
export function shown(value: number | null | undefined): string {
  if (value === null || value === undefined) return "?";
  return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

/** A 0..1 share as a whole percent (null: nothing measured yet). */
export function percent(value: number | null | undefined): number | null {
  return value === null || value === undefined ? null : Math.round(value * 100);
}

function utcDate(iso: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return null;
  const d = new Date(`${iso}T00:00:00Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "2026-12-31" → "Dec 31, 2026" (the text itself when it isn't a date). */
export function day(iso: string): string {
  const d = utcDate(iso);
  return d
    ? d.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
        timeZone: "UTC",
      })
    : iso;
}

/** "2026-10-27" → "Tuesday, Oct 27". */
export function weekday(iso: string): string {
  const d = utcDate(iso);
  return d
    ? d.toLocaleDateString("en-US", {
        weekday: "long",
        month: "short",
        day: "numeric",
        timeZone: "UTC",
      })
    : iso;
}

/** "2026-11-01" → "Nov 1" (short, for project ranges). */
export function shortDay(iso: string): string {
  const d = utcDate(iso);
  return d
    ? d.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        timeZone: "UTC",
      })
    : iso;
}

/** "Script Writer" → "SW", "Head of Content" → "HC", "editor" → "ED". */
export function initials(name: string): string {
  const all = name
    .trim()
    .split(/[\s_-]+/)
    .filter(Boolean);
  const big = all.filter((w) => /^[A-Z0-9]/.test(w));
  const words = big.length >= 2 ? big : all;
  const first = words[0] ?? "";
  const last = words.length > 1 ? (words[words.length - 1] ?? "") : "";
  if (!first) return "?";
  if (!last) return first.slice(0, 2).toUpperCase();
  return (first.slice(0, 1) + last.slice(0, 1)).toUpperCase();
}

export type Found = { node: PlanNode; goal: PlanNode | null };

/** Each goal and project by id, with the goal it belongs to (a goal: itself). */
export function planIndex(goals: PlanNode[]): Map<number, Found> {
  const out = new Map<number, Found>();
  for (const g of goals) {
    out.set(g.id, { node: g, goal: g });
    const stack = [...(g.children ?? [])];
    while (stack.length > 0) {
      const p = stack.pop();
      if (!p) break;
      out.set(p.id, { node: p, goal: g });
      stack.push(...(p.children ?? []));
    }
  }
  return out;
}
