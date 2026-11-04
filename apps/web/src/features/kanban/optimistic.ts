import type { KanbanBoard, KanbanCard } from "@/data/types";

// The Kanban's clicks shown at once (W10): while Hermes's own CLI write runs
// (~0.65 s, then ~0.7 s for the Kanban's re-read), the screen shows the card
// where the click sends it. Nothing here writes or keeps anything: the guess
// lives only as long as the click's transition (React's useOptimistic), then
// Hermes's real Kanban from the refresh replaces it, also when the write failed.
// Pure functions, so `pnpm test` checks them without React.

/** What the Kanban shows of a card: no body or criteria, so the page doesn't
 * send every card's text to the browser on each refresh. */
export type ShownCard = Pick<
  KanbanCard,
  | "id"
  | "title"
  | "status"
  | "blockKind"
  | "member"
  | "memberTitle"
  | "goal"
  | "model"
  | "attention"
  | "attentionWhy"
  | "holdId"
  | "goalId"
  | "goalInherited"
  | "chainStalled"
  | "reviewChip"
  | "labels"
  | "priority"
  | "createdAt"
> & {
  skillPins?: KanbanCard["skillPins"];
  /** The title of the goal it serves ("" = none), from the Kanban's goal list. */
  goalTitle: string;
};

export type ShownBoard = Pick<KanbanBoard, "columns" | "dispatchSeconds"> & {
  cards: ShownCard[];
};

/** One click whose Hermes write is still running: the fields it changes. */
export type CardChange = { card: string } & Partial<
  Pick<ShownCard, "status" | "blockKind" | "member" | "memberTitle">
>;

/** The Kanban as the page shows it (see ShownCard). */
export function boardOnScreen(board: KanbanBoard): ShownBoard {
  const titles = new Map((board.goals ?? []).map((g) => [g.id, g.title]));
  const goalTitle = (id: number | null | undefined) =>
    id === null || id === undefined ? "" : (titles.get(id) ?? `#${String(id)}`);
  return {
    columns: board.columns,
    dispatchSeconds: board.dispatchSeconds,
    cards: board.cards.map((c) => ({
      id: c.id,
      title: c.title,
      status: c.status,
      blockKind: c.blockKind,
      attention: c.attention,
      attentionWhy: c.attentionWhy,
      holdId: c.holdId,
      member: c.member,
      memberTitle: c.memberTitle,
      goal: c.goal,
      model: c.model,
      skillPins: c.skillPins,
      goalId: c.goalId,
      goalInherited: c.goalInherited,
      goalTitle: goalTitle(c.goalId),
      chainStalled: c.chainStalled,
      reviewChip: c.reviewChip,
      labels: c.labels,
      priority: c.priority,
      createdAt: c.createdAt,
    })),
  };
}

/** The card with the pending clicks on it, oldest first (the last click on a
 * field wins). The card itself is never changed: when the clicks end, the
 * screen simply shows Hermes's card again. */
export function withChanges<T extends { id: string }>(
  card: T,
  changes: readonly CardChange[],
): T {
  let out = card;
  for (const change of changes) {
    if (change.card !== card.id) continue;
    const { card: _id, ...fields } = change;
    out = { ...out, ...fields };
  }
  return out;
}

/** The Kanban with the pending clicks on it (the same Kanban when none). */
export function boardWithChanges(
  board: ShownBoard,
  changes: readonly CardChange[],
): ShownBoard {
  if (changes.length === 0) return board;
  return { ...board, cards: board.cards.map((c) => withChanges(c, changes)) };
}

/** Where Hermes puts a card after one of its buttons (hermes_cli/kanban_db.py:
 * complete -> done, archive -> archived, block -> blocked; unblock and the
 * owner's answer -> ready, or todo while a parent is not done or archived).
 * null when the screen can't tell for sure (a parent not on the Kanban, a
 * column the Kanban doesn't show): then nothing moves early, as before. */
export function landing(
  action: "unblock" | "archive" | "done" | "block",
  card: { parents?: readonly string[] },
  board: ShownBoard,
): string | null {
  let status: string;
  if (action === "done") status = "done";
  else if (action === "archive") status = "archived";
  else if (action === "block") status = "blocked";
  else {
    const parents = (card.parents ?? []).map((id) =>
      board.cards.find((c) => c.id === id),
    );
    if (parents.some((p) => p === undefined)) return null;
    status = parents.every(
      (p) => p?.status === "done" || p?.status === "archived",
    )
      ? "ready"
      : "todo";
  }
  return (board.columns ?? []).some((c) => c.status === status) ? status : null;
}
