import type { PlanNode } from "@/data/types";
import type { ItemChanges, ResultFields } from "./actions";
import { type KeyResult, type Kind, type Status } from "./goal-model";
import { num, parseNum } from "./goal-text";

export type ResultDraft = {
  id: number;
  title: string;
  current: string;
  target: string;
  unit: string;
  dueOn: string;
  gone: boolean;
};

export type ProjectDraft = {
  id: number;
  title: string;
  owner: string;
  status: Status;
  projectKind: Kind;
  startsOn: string;
  endsOn: string;
  rhythm: string;
  gone: boolean;
};

export function resultDraft(k: KeyResult): ResultDraft {
  return {
    id: k.id,
    title: k.title,
    current: num(k.current),
    target: k.target === null || k.target === undefined ? "" : num(k.target),
    unit: k.unit,
    dueOn: k.dueOn,
    gone: false,
  };
}

export function projectDraft(p: PlanNode): ProjectDraft {
  return {
    id: p.id,
    title: p.title,
    owner: p.owner,
    status: p.status,
    projectKind: p.projectKind === "recurring" ? "recurring" : "dated",
    startsOn: p.startsOn,
    endsOn: p.endsOn,
    rhythm: p.rhythm,
    gone: false,
  };
}

/** Only the fields that changed (the core takes partial updates). */
export function resultChanges(
  k: KeyResult,
  d: ResultDraft,
): ResultFields | string | null {
  const out: ResultFields = {};
  const title = d.title.trim();
  if (!title) return "Each key result needs a title.";
  if (title !== k.title) out.title = title;
  const current = parseNum(d.current);
  if (current === null || !Number.isFinite(current))
    return `“${title}”: the current value must be a number.`;
  if (current !== k.current) out.current = current;
  const target = parseNum(d.target);
  if (target !== null && !Number.isFinite(target))
    return `“${title}”: the target must be a number.`;
  if (target !== (k.target ?? null)) out.target = target;
  if (d.unit !== k.unit) out.unit = d.unit;
  if (d.dueOn !== k.dueOn) out.dueOn = d.dueOn;
  return Object.keys(out).length > 0 ? out : null;
}

export function projectChanges(
  p: PlanNode,
  d: ProjectDraft,
): ItemChanges | string | null {
  const out: ItemChanges = {};
  const title = d.title.trim();
  if (!title) return "Each project needs a title.";
  if (title !== p.title) out.title = title;
  if (d.owner !== p.owner) out.owner = d.owner;
  if (d.status !== p.status) out.status = d.status;
  if (d.projectKind !== (p.projectKind || "dated"))
    out.projectKind = d.projectKind;
  const startsOn = d.projectKind === "dated" ? d.startsOn : "";
  const endsOn = d.projectKind === "dated" ? d.endsOn : "";
  const rhythm = d.projectKind === "recurring" ? d.rhythm : "";
  if (startsOn !== p.startsOn) out.startsOn = startsOn;
  if (endsOn !== p.endsOn) out.endsOn = endsOn;
  if (rhythm !== p.rhythm) out.rhythm = rhythm;
  return Object.keys(out).length > 0 ? out : null;
}
