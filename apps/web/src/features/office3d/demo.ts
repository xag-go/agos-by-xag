/* Demo Mode: reproducible sample activity on the real team, clearly labelled.
 * Never mixed with live data. */

import type { KanbanCard } from "@/data/types";
import {
  type Move,
  type OfficeAgent,
  type Status,
} from "@/features/office/model";

const SCRIPT: Status[][] = [
  ["working", "working", "idle", "working", "working", "idle", "working"],
  ["working", "working", "working", "working", "waiting", "idle", "working"],
  ["working", "meeting", "meeting", "working", "waiting", "working", "meeting"],
  ["meeting", "meeting", "meeting", "working", "working", "working", "meeting"],
  ["working", "working", "idle", "blocked", "working", "idle", "working"],
  ["working", "idle", "working", "blocked", "idle", "working", "working"],
];
const TASKS = [
  "Draft the hook for Friday's reel",
  "Check the sources on the AI music story",
  "Pick three trending topics",
  "Log the new interview footage",
  "Tighten the brand voice notes",
  "Script v2 for the explainer",
];

export const DEMO_STEP_MS = 12000;

function fakeCard(
  a: OfficeAgent,
  i: number,
  step: number,
  status: string,
): KanbanCard {
  return {
    id: `demo-${a.key}-${String(step)}`,
    title: TASKS[(i + step) % TASKS.length] ?? "Demo task",
    body: "",
    status,
    statusLabel: status,
    member: a.key,
    memberTitle: a.title,
    createdAt: Math.floor(Date.now() / 1000) - 600,
    createdBy: "demo",
    labels: [],
    priority: 0,
    model: "",
    goal: false,
    blockKind: status === "blocked" ? "needs_input" : "",
    attention: "",
    attentionWhy: "",
    startedAt: null,
    completedAt: null,
    goalInherited: false,
    chainStalled: "",
  };
}

export function demoAgents(real: OfficeAgent[], step: number): OfficeAgent[] {
  const row = SCRIPT[step % SCRIPT.length] ?? [];
  let meeting = 0;
  let lounge = 0;
  return real.map((a, i) => {
    const status: Status = row[i % row.length] ?? "working";
    let place: OfficeAgent["place"] = "desk";
    let slot = 0;
    if (status === "meeting") {
      place = "meeting";
      slot = meeting++;
    } else if (status === "idle") {
      place = "lounge";
      slot = lounge++;
    }
    const cardStatus =
      status === "working"
        ? "running"
        : status === "waiting"
          ? "review"
          : status === "blocked"
            ? "blocked"
            : "todo";
    const current =
      status === "idle" || status === "free"
        ? null
        : fakeCard(a, i, step, cardStatus);
    return {
      ...a,
      status,
      place,
      slot,
      current,
      open: current ? [current] : [],
    };
  });
}

/** Each step the Co-Founder hands one new task over, and one task is finished. */
export function demoMoves(real: OfficeAgent[], step: number): Move[] {
  if (real.length < 2) return [];
  const to = real[1 + (step % (real.length - 1))];
  const done = real[1 + ((step + 2) % (real.length - 1))];
  const out: Move[] = [];
  if (to)
    out.push({ id: `demo-give-${String(step)}`, to: to.key, done: false });
  if (done)
    out.push({ id: `demo-done-${String(step)}`, to: done.key, done: true });
  return out;
}

export function demoEvents(real: OfficeAgent[], step: number) {
  const to = real[1 + (step % Math.max(1, real.length - 1))];
  const done = real[1 + ((step + 2) % Math.max(1, real.length - 1))];
  const now = Date.now() / 1000;
  return [
    to && {
      at: now,
      who: "Co-Founder",
      text: `handed “${TASKS[step % TASKS.length] ?? ""}” to ${to.title}`,
      kind: "handoff" as const,
    },
    done && {
      at: now - 1,
      who: done.title,
      text: "finished a task",
      kind: "done" as const,
    },
  ].filter(Boolean) as FeedEvent[];
}

export type FeedEvent = {
  at: number; // unix seconds
  who: string;
  text: string;
  kind: "handoff" | "start" | "done" | "blocked" | "review" | "new";
  cardId?: string;
};
