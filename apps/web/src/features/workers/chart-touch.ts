/**
 * The org chart's touch gestures and its phone-sized fit: one finger pans, two
 * fingers pinch-zoom, a finger landing on a box still pans (a tap opens it).
 * Also the mouse drag. Pure handlers over the chart's refs.
 */

import {
  useRef,
  type Dispatch,
  type PointerEvent,
  type SetStateAction,
} from "react";
import {
  BOX_W,
  MAX_ZOOM,
  MIN_ZOOM,
  PAD,
  READABLE_ZOOM,
  type Placed,
} from "./hierarchy-layout";

export type View = { x: number; y: number; k: number };
type Point = { x: number; y: number };
type Pinch = { d: number; cx: number; cy: number };
export type Drag = { x: number; y: number; vx: number; vy: number };

type Touch = {
  touches: Map<number, Point>;
  pinch: { current: Pinch | null };
  drag: { current: Drag | null };
  moved: { current: boolean };
  view: View;
  setView: Dispatch<SetStateAction<View>>;
};

/** A phone-sized pane: fitting the whole tree squeezes boxes into unreadable
 * specks. Clamp to a readable scale, centred on the root box; the rest is a
 * pan/pinch away. Null when the normal fit is readable. */
export function phoneFit(
  rootX: number | undefined,
  width: number,
  cw: number,
  k: number,
): View | null {
  if (cw >= 768 || k >= READABLE_ZOOM) return null;
  const rootCx = (rootX ?? (width - BOX_W) / 2) + BOX_W / 2;
  return { k: READABLE_ZOOM, x: cw / 2 - rootCx * READABLE_ZOOM, y: PAD / 2 };
}

/** The root box's left edge (chart px), a number so a fit can depend on it. */
export function rootXOf(placed: Placed[]): number | undefined {
  return placed.length > 0 ? placed[0]?.x : undefined;
}

function pinchOf(a: Point, b: Point, el: HTMLElement): Pinch {
  const r = el.getBoundingClientRect();
  return {
    d: Math.hypot(a.x - b.x, a.y - b.y),
    cx: (a.x + b.x) / 2 - r.left,
    cy: (a.y + b.y) / 2 - r.top,
  };
}

function fingerDown(t: Touch, event: PointerEvent<HTMLElement>) {
  // Seen before a box's stopPropagation: on touch, a pan or pinch must start
  // even when the finger lands on a box (the box's click only fires when
  // nothing moved).
  if (event.pointerType !== "touch") return;
  t.touches.set(event.pointerId, { x: event.clientX, y: event.clientY });
  if (t.touches.size === 2) {
    // Second finger: pan becomes a pinch-zoom.
    const [a, b] = [...t.touches.values()];
    if (a && b) {
      t.drag.current = null;
      t.moved.current = true;
      t.pinch.current = pinchOf(a, b, event.currentTarget);
    }
    return;
  }
  t.drag.current = {
    x: event.clientX,
    y: event.clientY,
    vx: t.view.x,
    vy: t.view.y,
  };
  t.moved.current = false;
}

/** Two fingers down: zoom around their centre. True when the move was a pinch. */
function pinchMove(t: Touch, event: PointerEvent<HTMLElement>): boolean {
  const finger = t.touches.get(event.pointerId);
  if (finger) {
    finger.x = event.clientX;
    finger.y = event.clientY;
  }
  const pz = t.pinch.current;
  if (!pz || t.touches.size !== 2) return false;
  const [a, b] = [...t.touches.values()];
  if (!a || !b) return true;
  const now = pinchOf(a, b, event.currentTarget);
  // Captured now: the updater runs batched, after pz is mutated.
  const grow = now.d > 0 && pz.d > 0 ? now.d / pz.d : 1;
  const px = pz.cx;
  const py = pz.cy;
  t.setView((v) => {
    const k = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, v.k * grow));
    const ratio = k / v.k;
    return {
      k,
      x: now.cx - (px - v.x) * ratio,
      y: now.cy - (py - v.y) * ratio,
    };
  });
  t.pinch.current = now;
  return true;
}

function mouseDown(t: Touch, event: PointerEvent<HTMLElement>) {
  if (event.pointerType === "touch") return;
  if (event.button !== 0) return;
  event.currentTarget.setPointerCapture(event.pointerId);
  t.drag.current = {
    x: event.clientX,
    y: event.clientY,
    vx: t.view.x,
    vy: t.view.y,
  };
  t.moved.current = false;
}

/** A pinch, else a pan (mouse drag or one finger). */
function anyMove(t: Touch, event: PointerEvent<HTMLElement>) {
  if (pinchMove(t, event)) return;
  const d = t.drag.current;
  if (!d) return;
  const dx = event.clientX - d.x;
  const dy = event.clientY - d.y;
  if (Math.abs(dx) + Math.abs(dy) > 3) t.moved.current = true;
  t.setView((v) => ({ ...v, x: d.vx + dx, y: d.vy + dy }));
}

function fingerUp(t: Touch, event: PointerEvent<HTMLElement>, cancel: boolean) {
  t.touches.delete(event.pointerId);
  t.pinch.current = null;
  t.drag.current = null;
  if (cancel) return;
  // One finger stays down: go on panning from where it is.
  if (t.touches.size === 1) {
    const [p] = [...t.touches.values()];
    if (p) t.drag.current = { x: p.x, y: p.y, vx: t.view.x, vy: t.view.y };
  }
}

/** The canvas's pointer handlers: mouse drag, one-finger pan, two-finger pinch. */
export function useChartTouch(
  drag: { current: Drag | null },
  moved: { current: boolean },
  view: View,
  setView: Dispatch<SetStateAction<View>>,
) {
  const touches = useRef(new Map<number, Point>());
  const pinch = useRef<Pinch | null>(null);
  const t = (): Touch => ({
    touches: touches.current,
    pinch,
    drag,
    moved,
    view,
    setView,
  });
  return {
    down: (event: PointerEvent<HTMLElement>) => {
      fingerDown(t(), event);
    },
    mouseDown: (event: PointerEvent<HTMLElement>) => {
      mouseDown(t(), event);
    },
    move: (event: PointerEvent<HTMLElement>) => {
      anyMove(t(), event);
    },
    up: (event: PointerEvent<HTMLElement>) => {
      fingerUp(t(), event, false);
    },
    cancel: (event: PointerEvent<HTMLElement>) => {
      fingerUp(t(), event, true);
    },
  };
}
