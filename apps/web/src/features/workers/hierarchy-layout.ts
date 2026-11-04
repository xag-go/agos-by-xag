import type { ModelSelection } from "@agos/core";
import type {
  CatalogProvider,
  LibraryItem,
  OrgEntry,
  Proposal,
  Team,
  Worker,
} from "@/data/types";
import { modelName } from "@/features/models/model-label";

export type Copyable = {
  id: number;
  title: string;
  name: string;
  workspace: string;
};

/** Where a box stands: working now, on the team, off it, or not hired yet. */
export type Status = "working" | "active" | "paused" | "pending";

/** One box of the chart. */
export type Node = {
  worker: Worker;
  agent: LibraryItem | null;
  /** A hire waiting for the owner's Approve: a ghost box in its future place. */
  pending: Proposal | null;
  model: string;
  status: Status;
  lead: boolean;
  children: Node[];
  /** Its chain of command and chain health (the core's derivation); null for
   * the Co-Founder and a pending hire. */
  org: OrgEntry | null;
};

export const STATUS_WORDS: Record<Status, string> = {
  working: "Working now",
  active: "Active",
  paused: "Paused",
  pending: "Pending approval",
};

/** Where the layout put a box (chart px, before zoom). */
export type Placed = { node: Node; x: number; y: number };

export const BOX_W = 264;
export const BOX_H = 92;
const GAP_X = 28;
export const GAP_Y = 76;
export const PAD = 40;
export const MIN_ZOOM = 0.3;
export const MAX_ZOOM = 2;

/**
 * The org chart: the Co-Founder on top; each member under who it reports to
 * (`definition.reports_to`, "" or an unknown name = the Co-Founder; a loop in the
 * data never hangs the layout); members off the team show paused; a hire
 * waiting for the owner is a ghost box under its future cofounder.
 */
export function buildTree(
  team: Team,
  agents: LibraryItem[],
  pending: Proposal[],
  cofounderModel: ModelSelection | null,
  catalog: CatalogProvider[],
): Node {
  const label = (m: ModelSelection | null | undefined) =>
    modelName(m ?? null, catalog);
  const workers = new Map(team.members.map((m) => [m.name ?? "", m]));
  const byName = new Map(agents.map((a) => [a.name, a]));
  const nodes = new Map<string, Node>();
  for (const agent of agents) {
    const def = agent.definition as {
      model?: ModelSelection;
      instructions?: string;
      reports_to?: string;
    };
    const worker: Worker = workers.get(agent.name) ?? {
      name: agent.name,
      title: agent.title,
      role: agent.summary || "Member",
      summary: firstLines(def.instructions ?? ""),
      dmChatId: null,
      working: false,
      profile: null,
    };
    const on = agent.usedBy.length > 0;
    nodes.set(agent.name, {
      worker,
      agent,
      pending: null,
      model: label(def.model),
      status: !on ? "paused" : worker.working ? "working" : "active",
      lead: false,
      children: [],
      org: team.org?.[agent.name] ?? null,
    });
  }
  const root: Node = {
    worker: team.cofounder,
    agent: null,
    pending: null,
    model: label(cofounderModel),
    status: team.cofounder.working ? "working" : "active",
    lead: true,
    children: [],
    org: null,
  };
  // Who is under whom; a name that would close a loop goes under the Co-Founder.
  const bossOf = (name: string): string => {
    const def = byName.get(name)?.definition as
      { reports_to?: string } | undefined;
    const boss = def?.reports_to ?? "";
    if (!boss || !nodes.has(boss) || boss === name) return "";
    let walk: string = boss;
    const seen = new Set([name]);
    while (walk) {
      if (seen.has(walk)) return "";
      seen.add(walk);
      const next = byName.get(walk)?.definition as
        { reports_to?: string } | undefined;
      walk =
        next?.reports_to && nodes.has(next.reports_to) ? next.reports_to : "";
    }
    return boss;
  };
  for (const [name, node] of nodes) {
    const boss = bossOf(name);
    (boss ? (nodes.get(boss)?.children ?? root.children) : root.children).push(
      node,
    );
  }
  for (const p of pending.filter((x) => x.kind === "hire")) {
    const payload = p.payload as {
      name?: string;
      title?: string;
      role?: string;
      model?: ModelSelection;
      reports_to?: string;
    };
    const under = payload.reports_to
      ? nodes.get(payload.reports_to)
      : undefined;
    (under ?? root).children.push({
      worker: {
        name: payload.name ?? null,
        title: payload.title ?? p.label,
        role: "Pending approval",
        summary: firstLines(payload.role ?? ""),
        dmChatId: null,
        working: false,
        profile: null,
      },
      agent: null,
      pending: p,
      model: label(payload.model ?? null),
      status: "pending",
      lead: false,
      children: [],
      org: null,
    });
  }
  const sortBoxes = (n: Node) => {
    n.children.sort((a, b) => a.worker.title.localeCompare(b.worker.title));
    n.children.forEach(sortBoxes);
  };
  sortBoxes(root);
  return root;
}

/** A stable key per box (a pending hire has no member yet). */
export function keyOf(node: Node): string {
  if (node.pending) return `pending-${String(node.pending.id)}`;
  return node.worker.name ?? "cofounder";
}

function firstLines(text: string, limit = 400): string {
  const lines = text
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith("#"));
  const out = lines.join(" ");
  return out.length > limit ? `${out.slice(0, limit)}…` : out;
}

/** A tidy tree: each subtree as wide as its children, parents centred. */
export function layout(root: Node): {
  placed: Placed[];
  width: number;
  height: number;
} {
  const placed: Placed[] = [];
  const widthOf = (n: Node): number =>
    n.children.length === 0
      ? BOX_W
      : Math.max(
          BOX_W,
          n.children.reduce((w, c) => w + widthOf(c), 0) +
            GAP_X * (n.children.length - 1),
        );
  let depth = 0;
  const place = (n: Node, left: number, level: number) => {
    depth = Math.max(depth, level);
    const w = widthOf(n);
    placed.push({
      node: n,
      x: left + (w - BOX_W) / 2,
      y: level * (BOX_H + GAP_Y),
    });
    let x = left;
    for (const c of n.children) {
      place(c, x, level + 1);
      x += widthOf(c) + GAP_X;
    }
  };
  place(root, 0, 0);
  return {
    placed,
    width: widthOf(root),
    height: (depth + 1) * BOX_H + depth * GAP_Y,
  };
}

/** The Founder's box at the Co-Founder's level, to its left (side by side, not
 * above): the chart moves right when there is no room for it. */
export function besideFounder(
  laid: { placed: Placed[]; width: number; height: number },
  shown: boolean,
): {
  placed: Placed[];
  width: number;
  height: number;
  founderAt: { x: number; y: number } | null;
} {
  const top = laid.placed[0];
  if (!shown || !top) return { ...laid, founderAt: null };
  const want = top.x - BOX_W - GAP_X * 2;
  const shift = Math.max(0, -want);
  return {
    placed: laid.placed.map((p) => ({ ...p, x: p.x + shift })),
    width: laid.width + shift,
    height: laid.height,
    founderAt: { x: want + shift, y: top.y },
  };
}
