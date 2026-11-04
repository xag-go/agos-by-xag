import type { PlanNode } from "@/data/types";
import { shortDay } from "./format";
import type { KeyResult, Member } from "./goal-model";

/** How a goal's values read on the page: its numbers, units, owners, a project's dates. */
export function num(value: number | null | undefined): string {
  if (value === null || value === undefined) return "?";
  return Number.isInteger(value)
    ? String(value)
    : String(Number(value.toFixed(2)));
}

/** "" for an empty box, a number, or NaN for words that aren't one. */
export function parseNum(text: string): number | null {
  return text.trim() ? Number(text) : null;
}

export function ownerName(owner: string, members: Member[]): string {
  if (!owner) return "";
  return members.find((m) => m.name === owner)?.title ?? `@${owner}`;
}

export function projectShape(p: PlanNode): string {
  if (p.projectKind === "recurring") return p.rhythm || "Recurring";
  if (p.startsOn && p.endsOn && p.startsOn.slice(0, 7) === p.endsOn.slice(0, 7))
    return `${shortDay(p.startsOn)} – ${String(Number(p.endsOn.slice(8)))}`;
  if (p.startsOn || p.endsOn)
    return `${p.startsOn ? shortDay(p.startsOn) : "?"} – ${p.endsOn ? shortDay(p.endsOn) : "?"}`;
  return "";
}

/** "Followers" is already in "Instagram followers": the unit only when new. */
export function unitFor(k: KeyResult): string {
  const unit = k.unit.trim();
  if (!unit || k.title.toLowerCase().includes(unit.toLowerCase())) return "";
  return ` ${unit}`;
}
