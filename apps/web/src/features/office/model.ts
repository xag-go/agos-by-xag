/* What the Office shows, worked out from live data only: the team (Hermes
 * profiles), the Kanban (Hermes's Kanban) and the chats. Nothing is stored. */

import type { KanbanCard, OfficeLook, Team } from "@/data/types";

export type Status =
  "waiting" | "meeting" | "working" | "blocked" | "idle" | "free";
export type Place = "desk" | "meeting" | "lounge";

export type OfficeAgent = {
  key: string; // "cofounder" or the agent's name
  title: string;
  role: string;
  look: OfficeLook;
  status: Status;
  place: Place;
  slot: number; // its seat in the meeting room or the lounge
  current: KanbanCard | null; // what it's on (or waits on) now
  open: KanbanCard[]; // its cards not done yet
  dmChatId: number | null;
};

/** The Kanban's open statuses (the core's columns with `open`: not done, not
 * archived), so a status Hermes adds counts by itself. */
export type OpenStatuses = ReadonlySet<string>;

export function openStatuses(
  columns: { status: string; open?: boolean }[],
): string[] {
  return columns.filter((c) => c.open).map((c) => c.status);
}

export function ownerOf(card: KanbanCard): string {
  return card.member === "" || card.member === "cofounder"
    ? "cofounder"
    : card.member;
}

const needsYou = (c: KanbanCard) =>
  c.status === "review" ||
  (c.status === "blocked" && c.blockKind === "needs_input");

export function officeAgents(
  team: Team,
  cards: KanbanCard[],
  looks: Record<string, OfficeLook>,
  openNow: OpenStatuses,
): OfficeAgent[] {
  const people = [team.cofounder, ...team.members];
  const inMeeting = new Set<string>();
  for (const g of team.groups) {
    if (!g.working) continue;
    for (const m of g.members) inMeeting.add(m === "" ? "cofounder" : m);
  }
  let lounge = 0;
  let meeting = 0;
  return people.map((w) => {
    const key = w.name ?? "cofounder";
    const open = cards
      .filter((c) => openNow.has(c.status) && ownerOf(c) === key)
      .sort((a, b) => b.createdAt - a.createdAt);
    const waiting = open.find(needsYou) ?? null;
    const running = open.find((c) => c.status === "running") ?? null;
    const sorting =
      key === "cofounder"
        ? (open.find((c) => c.status === "triage") ?? null)
        : null;
    const blocked = open.find((c) => c.status === "blocked") ?? null;
    let status: Status = "idle";
    if (waiting) status = "waiting";
    else if (inMeeting.has(key)) status = "meeting";
    else if (running || sorting || w.working) status = "working";
    else if (blocked) status = "blocked";
    let place: Place = "desk";
    let slot = 0;
    // the meeting room and the lounge have a seat for everyone in the team
    if (status === "meeting") {
      place = "meeting";
      slot = meeting++;
    } else if (status === "idle") {
      place = "lounge";
      slot = lounge++;
    }
    return {
      key,
      title: w.title,
      role: w.role,
      look: looks[key] ?? {
        pet: "none",
        petName: "",
        colour: "indigo",
        item: "plant",
      },
      status,
      place,
      slot,
      current: waiting ?? running ?? sorting ?? blocked ?? open[0] ?? null,
      open,
      dmChatId: w.dmChatId ?? null,
    };
  });
}

export type Seen = Record<string, { status: string; owner: string }>;

export function snapshot(cards: KanbanCard[]): Seen {
  const out: Seen = {};
  for (const c of cards) out[c.id] = { status: c.status, owner: ownerOf(c) };
  return out;
}

export type Move = { id: string; to: string; done: boolean };

/** Tasks that moved since the last look: handed out (Co-Founder → agent) or
 * finished (agent → the Done shelf). */
export function moves(before: Seen, now: Seen, open: OpenStatuses): Move[] {
  const out: Move[] = [];
  for (const [id, card] of Object.entries(now)) {
    const was = before[id];
    if (card.status === "done" && was && was.status !== "done") {
      out.push({ id: `${id}-done`, to: card.owner, done: true });
    } else if (
      open.has(card.status) &&
      card.owner !== "cofounder" &&
      (!was || was.owner !== card.owner)
    ) {
      out.push({ id: `${id}-to-${card.owner}`, to: card.owner, done: false });
    }
  }
  return out.slice(0, 8);
}

export function doneToday(cards: KanbanCard[], now: Date): number {
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  const since = start.getTime() / 1000;
  return cards.filter(
    (c) => c.status === "done" && (c.completedAt ?? 0) >= since,
  ).length;
}
