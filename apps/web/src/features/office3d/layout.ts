/* The 3D office floor plan, in metres. x runs left → right, z back → front,
 * y up. The back wall sits at z = 0 and the left wall at x = 0. */

export type V2 = { x: number; z: number };
export type Rect = { x: number; z: number; w: number; d: number }; // min corner + size

export type Seat = {
  id: string;
  /** Where the body sits (hips), and which way the person faces (radians, 0 = +z). */
  at: V2;
  face: number;
  /** Where the person stands before sitting down (outside every obstacle). */
  approach: V2;
  kind: "desk" | "meeting" | "sofa" | "armchair" | "stool" | "stand";
  seatY: number; // seat height
};

export type Station = {
  index: number; // -1 = Co-Founder
  desk: Rect;
  deskFace: number; // the way the sitter faces
  seat: Seat;
  monitor: V2; // monitor centre on the desk
};

const STUDIO_X = [7.7, 10, 12.3];
const DESK_W = 1.7;
const DESK_D = 0.8;
const CLUSTER_Z0 = 3.2; // back edge of the first cluster
const CLUSTER_STEP = 3.6;

export function clusters(members: number) {
  return Math.max(1, Math.ceil(members / 6));
}

/** Everyone in the team: the Co-Founder plus the members. */
const people = (members: number) => members + 1;

export function floorSize(members: number) {
  const l = lounge(members);
  return {
    w: 20,
    d: Math.max(
      13,
      CLUSTER_Z0 + clusters(members) * CLUSTER_STEP + 3.4,
      l.z + l.d + 0.3,
    ),
  };
}

export const COFOUNDER: Station = {
  index: -1,
  desk: { x: 2.3, z: 1.0, w: 1.0, d: 2.5 },
  deskFace: Math.PI / 2, // looks across the room (+x), seen from the side
  seat: {
    id: "desk-cofounder",
    at: { x: 1.75, z: 2.25 },
    face: Math.PI / 2,
    approach: { x: 1.6, z: 3.95 },
    kind: "desk",
    seatY: 0.48,
  },
  monitor: { x: 2.95, z: 2.25 },
};

/** The n-th member's workstation: desks in facing pairs, three per row. */
export function station(n: number): Station {
  const cluster = Math.floor(n / 6);
  const k = n % 6;
  const back = k < 3;
  const x = STUDIO_X[k % 3] ?? 10;
  const z0 = CLUSTER_Z0 + cluster * CLUSTER_STEP;
  const desk = {
    x: x - DESK_W / 2,
    z: back ? z0 : z0 + DESK_D,
    w: DESK_W,
    d: DESK_D,
  };
  const face = back ? 0 : Math.PI; // back row looks at the camera, front row at its screen
  const seatZ = back ? z0 - 0.45 : z0 + 2 * DESK_D + 0.45;
  return {
    index: n,
    desk,
    deskFace: face,
    seat: {
      id: `desk-${String(n)}`,
      at: { x, z: seatZ },
      face,
      approach: { x: x + 1.05, z: back ? z0 - 0.5 : z0 + 2 * DESK_D + 0.5 },
      kind: "desk",
      seatY: 0.48,
    },
    monitor: { x, z: back ? z0 + 0.5 : z0 + DESK_D + 0.3 },
  };
}

// ---- rooms ---------------------------------------------------------------

export const ZONES = {
  cofounder: { x: 0, z: 0, w: 5.6, d: 5.8 } as Rect,
  output: { x: 0, z: 6.6, w: 5.6, d: 6 } as Rect,
};

// The meeting room and the lounge grow with the team: a chair for everyone.
const SEAT_GAP = 0.9;
const TABLE_Z0 = 1.25;

/** Chairs on each long side of the meeting table. */
export function meetingRows(members: number) {
  return Math.max(3, Math.ceil(people(members) / 2));
}

export function meetingRoom(members: number): Rect {
  return {
    x: 14.6,
    z: 0,
    w: 5.4,
    d: TABLE_Z0 + meetingRows(members) * SEAT_GAP + 1.9,
  };
}

/** The long table, along the room (x, z = centre; rx, rz = half sizes). */
export function tableOf(members: number) {
  const len = meetingRows(members) * SEAT_GAP + 0.3;
  return { x: 17.3, z: TABLE_Z0 + len / 2, rx: 0.6, rz: len / 2 };
}

/** Meeting seats, filled left, right, left, right… from the top. */
export function meetingSeats(members: number): Seat[] {
  const rows = meetingRows(members);
  const out: Seat[] = [];
  for (let k = 0; k < rows * 2; k++) {
    const left = k % 2 === 0;
    const z = TABLE_Z0 + 0.6 + Math.floor(k / 2) * SEAT_GAP;
    const x = left ? 16.15 : 18.45;
    out.push({
      id: `meeting-${String(k)}`,
      at: { x, z },
      face: left ? Math.PI / 2 : -Math.PI / 2,
      approach: { x: left ? 15.35 : 19.3, z },
      kind: "meeting",
      seatY: 0.46,
    });
  }
  return out;
}

/** High tables with stools at the coffee corner: four stools each. */
export function barCount(members: number) {
  return Math.max(1, Math.ceil(Math.max(4, people(members) - 5) / 4));
}

export function lounge(members: number): Rect {
  const z = meetingRoom(members).d + 0.6;
  return { x: 14.6, z, w: 5.4, d: 3.4 + barCount(members) * 2.0 + 0.3 };
}

/** z of the k-th bar (its centre line). */
export function barZ(members: number, k: number) {
  return lounge(members).z + 3.92 + k * 2.0;
}

/** Lounge seats: the sofa, two armchairs, then stools at the bars. Enough for
 * the whole team. */
export function loungeSeats(members: number): Seat[] {
  const l = lounge(members);
  const sofaZ = l.z + 0.75;
  const seats: Seat[] = [16.5, 17.3, 18.1].map((x, i) => ({
    id: `sofa-${String(i)}`,
    at: { x, z: sofaZ },
    face: 0,
    approach: { x, z: sofaZ + 0.75 },
    kind: "sofa" as const,
    seatY: 0.42,
  }));
  seats.push(
    {
      id: "armchair-0",
      at: { x: 15.55, z: l.z + 2.35 },
      face: Math.PI / 2,
      approach: { x: 16.25, z: l.z + 2.35 },
      kind: "armchair",
      seatY: 0.42,
    },
    {
      id: "armchair-1",
      at: { x: 19.05, z: l.z + 2.35 },
      face: -Math.PI / 2,
      approach: { x: 18.35, z: l.z + 2.35 },
      kind: "armchair",
      seatY: 0.42,
    },
  );
  for (let k = 0; k < barCount(members); k++) {
    const z = barZ(members, k) - 0.72;
    for (let i = 0; i < 4; i++) {
      const at = { x: 16.2 + i * 0.75, z };
      seats.push({
        id: `stool-${String(k)}-${String(i)}`,
        at,
        face: 0,
        approach: { x: at.x, z: z - 0.42 },
        kind: "stool",
        seatY: 0.66,
      });
    }
  }
  return seats;
}

export const OUTPUT_SHELF: Rect = { x: 0.25, z: 6.9, w: 0.5, d: 3.2 };

// ---- what can't be walked through -----------------------------------------

export function obstacles(members: number): Rect[] {
  const out: Rect[] = [];
  const pad = (r: Rect, p: number): Rect => ({
    x: r.x - p,
    z: r.z - p,
    w: r.w + 2 * p,
    d: r.d + 2 * p,
  });
  out.push(pad(COFOUNDER.desk, 0.05));
  out.push({ x: 0, z: 0, w: 20, d: 0.35 }); // back wall + shelves
  out.push({ x: 0, z: 0, w: 0.35, d: floorSize(members).d }); // left wall
  for (let n = 0; n < members; n++) out.push(pad(station(n).desk, 0.05));
  // meeting room: glass walls, door at the bottom of the studio side
  const m = meetingRoom(members);
  out.push({ x: 14.5, z: 0, w: 0.15, d: m.d - 2.1 });
  out.push({ x: 14.5, z: m.d - 0.3, w: 0.15, d: 0.3 });
  out.push({ x: 14.5, z: m.d - 0.1, w: 5.5, d: 0.15 });
  const t = tableOf(members);
  out.push({ x: t.x - t.rx, z: t.z - t.rz, w: t.rx * 2, d: t.rz * 2 });
  // lounge furniture
  const l = lounge(members);
  out.push({ x: 15.8, z: l.z + 0.2, w: 3.0, d: 0.95 }); // sofa
  out.push({ x: 16.6, z: l.z + 1.85, w: 1.4, d: 0.8 }); // coffee table
  out.push({ x: 15.15, z: l.z + 1.95, w: 0.8, d: 0.8 });
  out.push({ x: 18.65, z: l.z + 1.95, w: 0.8, d: 0.8 });
  for (let k = 0; k < barCount(members); k++)
    out.push({ x: 15.6, z: barZ(members, k) - 0.32, w: 3.8, d: 0.65 }); // bars
  // output corner
  out.push(pad(OUTPUT_SHELF, 0.05));
  out.push({ x: 3.4, z: 9.25, w: 1.4, d: 0.7 }); // printer table
  out.push({ x: 4.85, z: 6.65, w: 0.4, d: 0.4 }); // water cooler
  out.push({ x: 0.5, z: 0.25, w: 1.7, d: 0.4 }); // Co-Founder's bookshelf
  out.push({ x: 0.85, z: 4.45, w: 3.6, d: 0.95 }); // Co-Founder's armchairs + table
  out.push(
    { x: 6.4, z: 1.8, w: 0.4, d: 0.4 },
    { x: 13.4, z: 1.8, w: 0.4, d: 0.4 },
  ); // floor lamps
  for (const p of plantSpots(members))
    out.push({ x: p.x - 0.3, z: p.z - 0.3, w: 0.6, d: 0.6 });
  return out;
}

/** Plants and other props that also block, placed where they look good. */
export function plantSpots(members: number): V2[] {
  const f = floorSize(members);
  return [
    { x: 5.15, z: 0.7 },
    { x: 13.9, z: 0.7 },
    { x: 0.7, z: 5.3 },
    { x: 0.7, z: f.d - 0.7 },
    { x: 13.9, z: f.d - 0.7 },
  ];
}
