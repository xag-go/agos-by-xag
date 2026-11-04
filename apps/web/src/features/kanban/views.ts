import type { ShownCard } from "./optimistic";

// The Kanban's views (Step 58): filters, group-by, sort, layout and the list's
// columns, all in the browser over the Kanban's one read (no extra Hermes call).
// The URL carries the view: `?view=<saved id>` and/or the fields themselves, so a
// link opens the same Kanban. Pure functions, so `pnpm test` checks them.

export type BoardGroup = "status" | "member" | "label" | "goal" | "project";
export type BoardSort =
  "created-desc" | "created-asc" | "title" | "priority" | "status";
export type BoardColumn =
  | "id"
  | "title"
  | "status"
  | "member"
  | "labels"
  | "goal"
  | "review"
  | "created"
  | "priority";
export type ReviewFilter =
  "" | "any" | "waiting" | "at_owner" | "stuck" | "none";
export type BlockedFilter = "" | "yes" | "no" | "asks";

export type BoardQuery = {
  members: string[];
  statuses: string[];
  labels: number[];
  goal: number | null;
  review: ReviewFilter;
  blocked: BlockedFilter;
  text: string;
  groupBy: BoardGroup;
  sort: BoardSort;
  layout: "board" | "list";
  columns: BoardColumn[];
  /** The saved view it started from (null: none). */
  view: number | null;
};

/** A saved view as the core keeps it (the owner's preferences row). */
export type SavedView = {
  id: number;
  name: string;
  filters?: {
    members?: string[];
    statuses?: string[];
    labels?: number[];
    goal?: number | null;
    review?: ReviewFilter;
    blocked?: BlockedFilter;
    text?: string;
  };
  groupBy?: BoardGroup;
  sort?: BoardSort;
  layout?: "board" | "list";
  columns?: BoardColumn[];
};

export type GoalNode = {
  id: number;
  parentId?: number | null;
  level?: string;
  title: string;
};

export const GROUPS: { value: BoardGroup; label: string }[] = [
  { value: "status", label: "Status" },
  { value: "member", label: "Member" },
  { value: "label", label: "Label" },
  { value: "goal", label: "Goal" },
  { value: "project", label: "Project" },
];
export const SORTS: { value: BoardSort; label: string }[] = [
  { value: "created-desc", label: "Newest first" },
  { value: "created-asc", label: "Oldest first" },
  { value: "title", label: "Title" },
  { value: "priority", label: "Priority" },
  { value: "status", label: "Status" },
];
export const COLUMNS: { value: BoardColumn; label: string }[] = [
  { value: "id", label: "Card" },
  { value: "title", label: "Title" },
  { value: "status", label: "Status" },
  { value: "member", label: "Member" },
  { value: "labels", label: "Labels" },
  { value: "goal", label: "Goal" },
  { value: "review", label: "Review" },
  { value: "created", label: "Created" },
  { value: "priority", label: "Priority" },
];
const DEFAULT_COLUMNS: BoardColumn[] = [
  "id",
  "title",
  "status",
  "member",
  "labels",
];

export const EMPTY_QUERY: BoardQuery = {
  members: [],
  statuses: [],
  labels: [],
  goal: null,
  review: "",
  blocked: "",
  text: "",
  groupBy: "status",
  sort: "created-desc",
  layout: "board",
  columns: DEFAULT_COLUMNS,
  view: null,
};

type Params = Record<string, string | string[] | undefined>;

const one = (v: string | string[] | undefined): string | undefined =>
  typeof v === "string" ? v : undefined;
const list = (v: string | undefined): string[] =>
  (v ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
const ids = (v: string | undefined): number[] =>
  list(v)
    .map(Number)
    .filter((n) => Number.isInteger(n) && n > 0);
const pick = <T extends string>(
  v: string | undefined,
  allowed: readonly T[],
  fallback: T,
): T => (allowed.includes(v as T) ? (v as T) : fallback);

/** The query a saved view stands for. */
export function queryOfView(view: SavedView): BoardQuery {
  const f = view.filters ?? {};
  return {
    members: f.members ?? [],
    statuses: f.statuses ?? [],
    labels: f.labels ?? [],
    goal: f.goal ?? null,
    review: f.review ?? "",
    blocked: f.blocked ?? "",
    text: f.text ?? "",
    groupBy: view.groupBy ?? "status",
    sort: view.sort ?? "created-desc",
    layout: view.layout ?? "board",
    columns: view.columns?.length ? view.columns : DEFAULT_COLUMNS,
    view: view.id,
  };
}

const REVIEWS = ["", "any", "waiting", "at_owner", "stuck", "none"] as const;
const BLOCKED = ["", "yes", "no", "asks"] as const;

/** The URL's view: a saved one (`view`), then each field the URL sets itself. */
export function queryFrom(params: Params, views: SavedView[]): BoardQuery {
  const viewId = Number(one(params.view));
  const saved = views.find((v) => v.id === viewId);
  const base = saved ? queryOfView(saved) : EMPTY_QUERY;
  const has = (k: string) => one(params[k]) !== undefined;
  const goal = Number(one(params.goal));
  return {
    members: has("m") ? list(one(params.m)) : base.members,
    statuses: has("st") ? list(one(params.st)) : base.statuses,
    labels: has("lb") ? ids(one(params.lb)) : base.labels,
    goal: has("goal")
      ? Number.isInteger(goal) && goal > 0
        ? goal
        : null
      : base.goal,
    review: has("rv") ? pick(one(params.rv), REVIEWS, "") : base.review,
    blocked: has("bl") ? pick(one(params.bl), BLOCKED, "") : base.blocked,
    text: has("q") ? (one(params.q) ?? "").slice(0, 200) : base.text,
    groupBy: has("group")
      ? pick(
          one(params.group),
          GROUPS.map((g) => g.value),
          base.groupBy,
        )
      : base.groupBy,
    sort: has("sort")
      ? pick(
          one(params.sort),
          SORTS.map((s) => s.value),
          base.sort,
        )
      : base.sort,
    layout: has("layout")
      ? pick(one(params.layout), ["board", "list"] as const, base.layout)
      : base.layout,
    columns: has("cols")
      ? (list(one(params.cols)).filter((c) =>
          COLUMNS.some((x) => x.value === c),
        ) as BoardColumn[])
      : base.columns,
    view: saved ? saved.id : null,
  };
}

/** The URL for a query: the saved view's id plus only what differs from it. */
export function queryString(q: BoardQuery, views: SavedView[]): string {
  const saved = views.find((v) => v.id === q.view);
  const base = saved ? queryOfView(saved) : EMPTY_QUERY;
  const out = new URLSearchParams();
  if (saved) out.set("view", String(saved.id));
  const same = (a: unknown, b: unknown) =>
    JSON.stringify(a) === JSON.stringify(b);
  if (!same(q.members, base.members)) out.set("m", q.members.join(","));
  if (!same(q.statuses, base.statuses)) out.set("st", q.statuses.join(","));
  if (!same(q.labels, base.labels)) out.set("lb", q.labels.join(","));
  if (q.goal !== base.goal)
    out.set("goal", q.goal === null ? "" : String(q.goal));
  if (q.review !== base.review) out.set("rv", q.review);
  if (q.blocked !== base.blocked) out.set("bl", q.blocked);
  if (q.text !== base.text) out.set("q", q.text);
  if (q.groupBy !== base.groupBy) out.set("group", q.groupBy);
  if (q.sort !== base.sort) out.set("sort", q.sort);
  if (q.layout !== base.layout) out.set("layout", q.layout);
  if (!same(q.columns, base.columns)) out.set("cols", q.columns.join(","));
  return out.toString();
}

/** Whether any filter is on (the toolbar's "Clear"). */
export function filtered(q: BoardQuery): boolean {
  return (
    q.members.length > 0 ||
    q.statuses.length > 0 ||
    q.labels.length > 0 ||
    q.goal !== null ||
    q.review !== "" ||
    q.blocked !== "" ||
    q.text.trim() !== ""
  );
}

/** The goal and every goal under it (a card serving a sub-goal serves it too). */
function under(goal: number, goals: GoalNode[]): Set<number> {
  const out = new Set([goal]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const g of goals)
      if (
        g.parentId !== null &&
        g.parentId !== undefined &&
        out.has(g.parentId) &&
        !out.has(g.id)
      ) {
        out.add(g.id);
        grew = true;
      }
  }
  return out;
}

/** The nearest goal at this level from the card's goal up (itself included). */
export function goalAt(
  goalId: number | null | undefined,
  level: "goal" | "project",
  goals: GoalNode[],
): GoalNode | null {
  const byId = new Map(goals.map((g) => [g.id, g]));
  let at =
    goalId === null || goalId === undefined ? undefined : byId.get(goalId);
  for (let hops = 0; at && hops < 20; hops++) {
    if ((at.level ?? "goal") === level) return at;
    at =
      at.parentId === null || at.parentId === undefined
        ? undefined
        : byId.get(at.parentId);
  }
  return null;
}

function reviewOk(card: ShownCard, review: ReviewFilter): boolean {
  const chip = card.reviewChip ?? null;
  switch (review) {
    case "":
      return true;
    case "any":
      return chip !== null;
    case "none":
      return chip === null;
    case "waiting":
      return card.status === "review";
    case "at_owner":
      return card.status === "review" && card.member === "owner";
    case "stuck":
      return chip?.phase === "stuck";
  }
}

function blockedOk(card: ShownCard, blocked: BlockedFilter): boolean {
  if (blocked === "") return true;
  const is = card.status === "blocked";
  if (blocked === "yes") return is;
  if (blocked === "no") return !is;
  return is && card.blockKind === "needs_input";
}

/** The cards the query shows, in its order. */
export function visibleCards(
  cards: ShownCard[],
  q: BoardQuery,
  goals: GoalNode[],
): ShownCard[] {
  const text = q.text.trim().toLowerCase();
  const goalSet = q.goal === null ? null : under(q.goal, goals);
  const out = cards.filter(
    (c) =>
      (q.members.length === 0 ||
        q.members.includes(c.member || (c.memberTitle ? "cofounder" : ""))) &&
      (q.statuses.length === 0 || q.statuses.includes(c.status)) &&
      (q.labels.length === 0 ||
        q.labels.some((l) => (c.labels ?? []).includes(l))) &&
      (goalSet === null ||
        (c.goalId !== null &&
          c.goalId !== undefined &&
          goalSet.has(c.goalId))) &&
      reviewOk(c, q.review) &&
      blockedOk(c, q.blocked) &&
      (!text ||
        [c.id, c.title, c.memberTitle, c.goalTitle].some((s) =>
          (s ?? "").toLowerCase().includes(text),
        )),
  );
  return sortCards(out, q.sort);
}

function sortCards(cards: ShownCard[], sort: BoardSort): ShownCard[] {
  const by = [...cards];
  const created = (c: ShownCard) => c.createdAt ?? 0;
  if (sort === "created-desc") by.sort((a, b) => created(b) - created(a));
  if (sort === "created-asc") by.sort((a, b) => created(a) - created(b));
  if (sort === "title") by.sort((a, b) => a.title.localeCompare(b.title));
  if (sort === "priority")
    by.sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0));
  if (sort === "status") by.sort((a, b) => a.status.localeCompare(b.status));
  return by;
}

export type Group = { key: string; label: string; cards: ShownCard[] };

/** The cards in groups (a card with two labels is in both label groups). Status
 * groups follow Hermes's columns; the others the order they first appear, with
 * the "none" group last. */
export function groupCards(
  cards: ShownCard[],
  groupBy: BoardGroup,
  ctx: {
    columns: { status: string; label: string }[];
    labels: { id: number; name: string }[];
    goals: GoalNode[];
  },
): Group[] {
  if (groupBy === "status")
    return ctx.columns.map((c) => ({
      key: c.status,
      label: c.label,
      cards: cards.filter((card) => card.status === c.status),
    }));
  const groups = new Map<string, Group>();
  const add = (key: string, label: string, card: ShownCard) => {
    const g = groups.get(key) ?? { key, label, cards: [] };
    g.cards.push(card);
    groups.set(key, g);
  };
  const names = new Map(ctx.labels.map((l) => [l.id, l.name]));
  for (const card of cards) {
    if (groupBy === "member")
      add(
        card.member || (card.memberTitle ? "cofounder" : ""),
        card.memberTitle ||
          (card.member === "owner" ? "You" : card.member || "Nobody yet"),
        card,
      );
    else if (groupBy === "label") {
      const mine = (card.labels ?? []).filter((l) => names.has(l));
      if (mine.length === 0) add("", "No label", card);
      for (const l of mine) add(String(l), names.get(l) ?? "", card);
    } else {
      const at = goalAt(card.goalId, groupBy, ctx.goals);
      add(
        at ? String(at.id) : "",
        at ? at.title : groupBy === "goal" ? "No goal" : "No project",
        card,
      );
    }
  }
  const out = [...groups.values()];
  return [...out.filter((g) => g.key), ...out.filter((g) => !g.key)];
}
