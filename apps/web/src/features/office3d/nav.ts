/* Walking routes: A* on a 0.2 m grid of the floor, around every obstacle,
 * then smoothed so people walk in straight lines where they can. */

import { floorSize, obstacles, type Rect, type V2 } from "./layout";

const CELL = 0.2;
const RADIUS = 0.24; // a person's half-width plus a little room

export type NavGrid = { cols: number; rows: number; blocked: Uint8Array };

export function makeGrid(members: number): NavGrid {
  const f = floorSize(members);
  const cols = Math.ceil(f.w / CELL);
  const rows = Math.ceil(f.d / CELL);
  const blocked = new Uint8Array(cols * rows);
  const mark = (r: Rect) => {
    const x0 = Math.max(0, Math.floor((r.x - RADIUS) / CELL));
    const x1 = Math.min(cols - 1, Math.floor((r.x + r.w + RADIUS) / CELL));
    const z0 = Math.max(0, Math.floor((r.z - RADIUS) / CELL));
    const z1 = Math.min(rows - 1, Math.floor((r.z + r.d + RADIUS) / CELL));
    for (let z = z0; z <= z1; z++)
      for (let x = x0; x <= x1; x++) blocked[z * cols + x] = 1;
  };
  for (const r of obstacles(members)) mark(r);
  // the floor's own edges
  for (let x = 0; x < cols; x++) {
    blocked[x] = 1;
    blocked[(rows - 1) * cols + x] = 1;
  }
  for (let z = 0; z < rows; z++) {
    blocked[z * cols] = 1;
    blocked[z * cols + cols - 1] = 1;
  }
  return { cols, rows, blocked };
}

const cellOf = (g: NavGrid, p: V2) => ({
  x: Math.min(g.cols - 1, Math.max(0, Math.floor(p.x / CELL))),
  z: Math.min(g.rows - 1, Math.max(0, Math.floor(p.z / CELL))),
});
const free = (g: NavGrid, x: number, z: number) =>
  x >= 0 &&
  z >= 0 &&
  x < g.cols &&
  z < g.rows &&
  g.blocked[z * g.cols + x] === 0;

/** The nearest walkable cell (people may start inside a chair or a sofa). */
function nearestFree(g: NavGrid, x: number, z: number) {
  if (free(g, x, z)) return { x, z };
  for (let r = 1; r < 30; r++) {
    for (let dz = -r; dz <= r; dz++)
      for (let dx = -r; dx <= r; dx++) {
        if (Math.max(Math.abs(dx), Math.abs(dz)) !== r) continue;
        if (free(g, x + dx, z + dz)) return { x: x + dx, z: z + dz };
      }
  }
  return { x, z };
}

function lineFree(g: NavGrid, a: V2, b: V2) {
  const steps = Math.ceil(Math.hypot(b.x - a.x, b.z - a.z) / (CELL / 2));
  for (let i = 0; i <= steps; i++) {
    const t = steps === 0 ? 0 : i / steps;
    const c = cellOf(g, { x: a.x + (b.x - a.x) * t, z: a.z + (b.z - a.z) * t });
    if (!free(g, c.x, c.z)) return false;
  }
  return true;
}

/** A walkable route from a to b (both included), or [] when there is none. */
export function findPath(g: NavGrid, from: V2, to: V2): V2[] {
  const s = nearestFree(g, cellOf(g, from).x, cellOf(g, from).z);
  const e = nearestFree(g, cellOf(g, to).x, cellOf(g, to).z);
  const n = g.cols * g.rows;
  const gScore = new Float32Array(n).fill(Infinity);
  const came = new Int32Array(n).fill(-1);
  const closed = new Uint8Array(n);
  const start = s.z * g.cols + s.x;
  const goal = e.z * g.cols + e.x;
  gScore[start] = 0;
  // small binary heap of [f, index]
  const heap: [number, number][] = [[0, start]];
  const push = (item: [number, number]) => {
    heap.push(item);
    let i = heap.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if ((heap[p]?.[0] ?? 0) <= item[0]) break;
      heap[i] = heap[p] as [number, number];
      i = p;
    }
    heap[i] = item;
  };
  const pop = (): [number, number] | undefined => {
    const top = heap[0];
    const last = heap.pop();
    if (heap.length > 0 && last) {
      let i = 0;
      for (;;) {
        const l = 2 * i + 1;
        const r = l + 1;
        let m = i;
        if (
          l < heap.length &&
          (heap[l]?.[0] ?? 0) < (m === i ? last[0] : (heap[m]?.[0] ?? 0))
        )
          m = l;
        if (
          r < heap.length &&
          (heap[r]?.[0] ?? 0) < (m === i ? last[0] : (heap[m]?.[0] ?? 0))
        )
          m = r;
        if (m === i) break;
        heap[i] = heap[m] as [number, number];
        i = m;
      }
      heap[i] = last;
    }
    return top;
  };
  const h = (i: number) => {
    const x = i % g.cols;
    const z = Math.floor(i / g.cols);
    const dx = Math.abs(x - e.x);
    const dz = Math.abs(z - e.z);
    return Math.max(dx, dz) + 0.414 * Math.min(dx, dz);
  };
  let found = start === goal;
  while (heap.length > 0 && !found) {
    const item = pop();
    if (!item) break;
    const cur = item[1];
    if (closed[cur]) continue;
    closed[cur] = 1;
    if (cur === goal) {
      found = true;
      break;
    }
    const cx = cur % g.cols;
    const cz = Math.floor(cur / g.cols);
    for (let dz = -1; dz <= 1; dz++)
      for (let dx = -1; dx <= 1; dx++) {
        if (!dx && !dz) continue;
        const nx = cx + dx;
        const nz = cz + dz;
        if (!free(g, nx, nz)) continue;
        if (dx && dz && (!free(g, cx + dx, cz) || !free(g, cx, cz + dz)))
          continue;
        const ni = nz * g.cols + nx;
        const cost = (gScore[cur] ?? 0) + (dx && dz ? 1.414 : 1);
        if (cost < (gScore[ni] ?? Infinity)) {
          gScore[ni] = cost;
          came[ni] = cur;
          push([cost + h(ni), ni]);
        }
      }
  }
  if (!found) return [];
  const cells: V2[] = [];
  for (let i = goal; i !== -1; i = came[i] ?? -1) {
    cells.push({
      x: ((i % g.cols) + 0.5) * CELL,
      z: (Math.floor(i / g.cols) + 0.5) * CELL,
    });
    if (i === start) break;
  }
  cells.reverse();
  const raw = [from, ...cells.slice(1, -1), to];
  // string-pulling: keep a point only when the straight line is blocked
  const out: V2[] = [raw[0] ?? from];
  let anchor = 0;
  for (let i = 2; i < raw.length; i++) {
    const a = raw[anchor];
    const b = raw[i];
    if (a && b && !lineFree(g, a, b)) {
      const keep = raw[i - 1];
      if (keep) out.push(keep);
      anchor = i - 1;
    }
  }
  out.push(to);
  return out;
}
