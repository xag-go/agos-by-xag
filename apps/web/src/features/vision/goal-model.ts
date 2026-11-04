import type { PlanNode, VisionView } from "@/data/types";

/** A goal's pieces as the vision page uses them, and its counting rules. */
export type Member = NonNullable<VisionView["members"]>[number];
export type KeyResult = NonNullable<PlanNode["results"]>[number];
export type Status = PlanNode["status"];
export type Kind = "dated" | "recurring";

/** The core's cap on projects per goal (actions/goals.py PROJECTS_MAX). */
export const PROJECTS_MAX = 5;

export function cardsOf(n: PlanNode): number {
  return n.cards.done + n.cards.open + n.cards.blocked;
}

/** A key result has started once its number moved off its start. */
export function started(k: KeyResult): boolean {
  return (k.progress ?? 0) > 0;
}
