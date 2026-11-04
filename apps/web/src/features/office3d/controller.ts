/* Each person's behaviour: where they're going, how they get there, and what
 * they're doing once they arrive. One controller per agent, updated per frame.
 * Positions and destinations come from the real state; only idle fidgets are
 * decorative. */

import type { OfficeAgent } from "@/features/office/model";
import {
  COFOUNDER,
  loungeSeats,
  meetingSeats,
  type Seat,
  station,
  type V2,
} from "./layout";
import { findPath, type NavGrid } from "./nav";

export type Activity =
  | "working"
  | "thinking"
  | "waiting"
  | "blocked"
  | "meeting"
  | "break"
  | "idle"
  | "offline";

export type Phase = "seated" | "standUp" | "walk" | "sitDown" | "stand";

type Step =
  | { kind: "go"; seat: Seat }
  | { kind: "visit"; at: V2; face: number; hold: number; give: boolean };

export type Ctl = {
  key: string;
  pos: V2;
  heading: number;
  phase: Phase;
  t: number; // seconds in this phase
  walk: number; // stride phase
  seat: Seat; // where they sit (or stand) when they arrive
  home: Seat; // their desk
  path: V2[];
  plan: Step[];
  activity: Activity;
  carrying: boolean;
  waitFor: number; // seconds spent waiting for someone in the way
  // after waiting, walk on regardless until this time
  passUntil: number;
  speed: number; // m/s on the current route
  rand: () => number;
  fidget: {
    kind: "none" | "glance" | "stretch" | "think" | "sip" | "gesture";
    until: number;
    next: number;
  };
};

const SPEED = 1.4; // m/s, a normal walk
// The real work doesn't wait for the walk: whatever the distance, people get
// there in this many seconds (they hurry on long routes), so they're already in
// place when their task starts or their message arrives.
const MAX_TRIP = 2.4;
const STAND = 0.35; // s to get up / sit down

function seeded(seed: string) {
  let h = 2166136261;
  for (const c of seed) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return () => {
    h = Math.imul(h ^ (h >>> 15), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    return ((h ^= h >>> 16) >>> 0) / 4294967296;
  };
}

export function homeSeat(index: number): Seat {
  return index === 0 ? COFOUNDER.seat : station(index - 1).seat;
}

export function seatFor(a: OfficeAgent, index: number, members: number): Seat {
  if (a.place === "meeting")
    return meetingSeats(members)[a.slot] ?? homeSeat(index);
  if (a.place === "lounge")
    return loungeSeats(members)[a.slot] ?? homeSeat(index);
  return homeSeat(index);
}

export function activityOf(a: OfficeAgent, offline: boolean): Activity {
  if (offline) return "offline";
  switch (a.status) {
    case "working":
      return "working";
    case "waiting":
      return "waiting";
    case "blocked":
      return "blocked";
    case "meeting":
      return "meeting";
    case "idle":
      return "break";
    case "free":
      return "idle";
  }
}

export function makeCtl(key: string, seat: Seat, home: Seat): Ctl {
  const rand = seeded(key);
  return {
    key,
    pos: { ...seat.at },
    heading: seat.face,
    phase: seat.kind === "stand" ? "stand" : "seated",
    t: rand() * 10,
    walk: 0,
    seat,
    home,
    path: [],
    plan: [],
    activity: "idle",
    carrying: false,
    waitFor: 0,
    passUntil: 0,
    speed: SPEED,
    rand,
    fidget: { kind: "none", until: 0, next: 3 + rand() * 8 },
  };
}

/** Send someone somewhere new (from wherever they are now). */
export function goTo(c: Ctl, seat: Seat) {
  if (c.seat.id === seat.id && c.plan.length === 0 && c.phase !== "walk")
    return;
  const busy = c.plan[0]?.kind === "visit";
  c.plan = busy
    ? [c.plan[0] as Step, { kind: "go", seat }]
    : [{ kind: "go", seat }];
  if (!busy) begin(c);
}

/** The Co-Founder walks a new task over to someone's desk, then returns. */
export function handOff(c: Ctl, to: Seat, back: Seat) {
  const side = to.face === 0 ? -1 : 1; // stand on the far side of the sitter's desk
  const at = { x: to.at.x - 0.75, z: to.at.z + side * 0.05 };
  c.plan = [
    {
      kind: "visit",
      at,
      face: Math.atan2(to.at.x - at.x, to.at.z - at.z),
      hold: 1.6,
      give: true,
    },
    { kind: "go", seat: back },
  ];
  c.carrying = true;
  begin(c);
}

function begin(c: Ctl) {
  if (c.phase === "seated") {
    c.phase = "standUp";
    c.t = 0;
  } else if (c.phase !== "standUp" && c.phase !== "sitDown") {
    route(c);
  }
}

let grid: NavGrid | null = null;
export function setGrid(g: NavGrid) {
  grid = g;
}

function route(c: Ctl) {
  const step = c.plan[0];
  if (!step || !grid) return;
  const target = step.kind === "go" ? step.seat.approach : step.at;
  const path = findPath(grid, c.pos, target);
  c.path = path.length > 0 ? path.slice(1) : [target];
  let length = 0;
  let from = c.pos;
  for (const p of c.path) {
    length += Math.hypot(p.x - from.x, p.z - from.z);
    from = p;
  }
  c.speed = Math.max(SPEED, length / MAX_TRIP);
  c.phase = "walk";
  c.t = 0;
}

function arrive(c: Ctl) {
  const step = c.plan[0];
  if (!step) {
    c.phase = "stand";
    return;
  }
  if (step.kind === "go") {
    c.seat = step.seat;
    c.plan.shift();
    if (step.seat.kind === "stand") {
      c.phase = "stand";
      c.heading = step.seat.face;
    } else {
      c.phase = "sitDown";
    }
    c.t = 0;
  } else {
    c.phase = "stand";
    c.heading = step.face;
    c.t = 0;
  }
}

const angleTo = (from: number, to: number) => {
  let d = to - from;
  while (d > Math.PI) d -= Math.PI * 2;
  while (d < -Math.PI) d += Math.PI * 2;
  return d;
};

/** One frame of behaviour. `others` lets people wait for each other. */
export function tick(c: Ctl, dt: number, others: Ctl[], still: boolean) {
  c.t += dt;
  if (still) {
    // reduced motion: jump straight to the destination
    const step = c.plan.find((s) => s.kind === "go");
    if (step && step.kind === "go") {
      c.seat = step.seat;
      c.pos = { ...step.seat.at };
      c.heading = step.seat.face;
    }
    c.plan = [];
    c.path = [];
    c.carrying = false;
    c.phase = c.seat.kind === "stand" ? "stand" : "seated";
    return;
  }
  switch (c.phase) {
    case "standUp": {
      // slide from the seat back to where they stood
      const k = Math.min(1, c.t / STAND);
      c.pos = lerp2(c.seat.at, c.seat.approach, ease(k));
      if (k >= 1) route(c);
      break;
    }
    case "sitDown": {
      const k = Math.min(1, c.t / STAND);
      c.pos = lerp2(c.seat.approach, c.seat.at, ease(k));
      c.heading += angleTo(c.heading, c.seat.face) * Math.min(1, dt * 10);
      if (k >= 1) {
        c.pos = { ...c.seat.at };
        c.heading = c.seat.face;
        c.phase = "seated";
        c.t = 0;
      }
      break;
    }
    case "walk": {
      const next = c.path[0];
      if (!next) {
        arrive(c);
        break;
      }
      const dx = next.x - c.pos.x;
      const dz = next.z - c.pos.z;
      const dist = Math.hypot(dx, dz);
      const want = Math.atan2(dx, dz);
      c.heading += angleTo(c.heading, want) * Math.min(1, dt * 8);
      // someone right in front: wait a moment, then carry on
      const blocker = others.find((o) => {
        if (o === c || o.phase === "seated") return false;
        const ox = o.pos.x - c.pos.x;
        const oz = o.pos.z - c.pos.z;
        const d = Math.hypot(ox, oz);
        if (d >= 0.6 || (ox * dx + oz * dz) / (d * dist + 1e-6) <= 0.6)
          return false;
        // walking the same way: just follow, no need to stop
        return !(
          o.phase === "walk" && Math.abs(angleTo(o.heading, want)) < 1.0
        );
      });
      // only the one with the lower name gives way, so two people never wait for each other
      const yields = blocker && c.t > c.passUntil && c.key > blocker.key;
      if (yields && c.waitFor < 0.35) {
        c.waitFor += dt;
        break;
      }
      if (c.waitFor >= 0.35) c.passUntil = c.t + 1.5;
      c.waitFor = 0;
      const step = c.speed * dt;
      c.walk += dt * 6.4 * Math.min(1.6, c.speed / SPEED);
      if (dist <= step) {
        c.pos = { ...next };
        c.path.shift();
        if (c.path.length === 0) arrive(c);
      } else {
        c.pos = {
          x: c.pos.x + (dx / dist) * step,
          z: c.pos.z + (dz / dist) * step,
        };
      }
      break;
    }
    case "stand": {
      const step = c.plan[0];
      if (step && step.kind === "visit") {
        if (c.t > step.hold * 0.55) c.carrying = false; // handed over
        if (c.t >= step.hold) {
          c.plan.shift();
          c.carrying = false;
          route(c);
        }
      } else if (step) {
        route(c);
      }
      break;
    }
    case "seated":
      break;
  }

  // decorative fidgets, staggered per person, only while settled
  const settled =
    c.phase === "seated" || (c.phase === "stand" && c.plan.length === 0);
  const f = c.fidget;
  if (f.kind !== "none" && c.t > f.until) f.kind = "none";
  if (settled && f.kind === "none") {
    f.next -= dt;
    if (f.next <= 0) {
      const r = c.rand();
      const pick: Record<Activity, Ctl["fidget"]["kind"][]> = {
        working: ["think", "glance", "think"],
        thinking: ["think"],
        waiting: ["glance", "stretch"],
        blocked: ["think", "glance"],
        meeting: ["gesture", "glance", "gesture"],
        break: ["sip", "glance", "sip"],
        idle: ["glance", "stretch", "glance"],
        offline: ["none"],
      };
      const options = pick[c.activity];
      f.kind = options[Math.floor(r * options.length)] ?? "none";
      f.until =
        c.t + (f.kind === "stretch" ? 2.2 : f.kind === "think" ? 2.6 : 1.6);
      f.next = 5 + c.rand() * 11;
    }
  }
}

function lerp2(a: V2, b: V2, k: number): V2 {
  return { x: a.x + (b.x - a.x) * k, z: a.z + (b.z - a.z) * k };
}
function ease(k: number) {
  return k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2;
}
