"use client";

import {
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useTransition,
} from "react";
import { saveWorkspaceOrder } from "@/features/settings/preferences-actions";

/** A mouse drag starts after this many pixels (below it, it's a click). */
const MOUSE_SLOP = 4;
/** A finger rests this long on a tile before it picks it up, so a tap still
 * opens the workspace. */
const TOUCH_HOLD_MS = 320;
/** A finger that moves this far before the hold ends is not dragging. */
const TOUCH_SLOP = 8;

/** The tile being dragged, as the rail draws it. */
type Shown = {
  id: string;
  from: number;
  to: number;
  dy: number;
  /** Each tile's centre (viewport y) when the drag began, in the shown order. */
  slots: number[];
};

type Press = Shown & {
  pointerId: number;
  startY: number;
  active: boolean;
  timer: ReturnType<typeof setTimeout> | undefined;
};

function moved<T>(list: T[], from: number, to: number): T[] {
  const next = list.slice();
  const [item] = next.splice(from, 1);
  if (item !== undefined) next.splice(to, 0, item);
  return next;
}

/** The slot nearest to where the dragged tile's centre is now. */
function slotAt(p: Press, y: number): number {
  const at = (p.slots[p.from] ?? 0) + y - p.startY;
  let best = p.from;
  p.slots.forEach((c, i) => {
    if (Math.abs(c - at) < Math.abs((p.slots[best] ?? 0) - at)) best = i;
  });
  return best;
}

/**
 * Drag a workspace tile up or down the rail to put it where you want it (a
 * finger holds it a moment first). The new order shows at once and is saved
 * for the account, so every screen gets it. Alt + ↑/↓ moves the focused tile.
 */
export function useRailOrder<W extends { id: string }>(
  workspaces: W[],
  onDragStart: () => void,
) {
  // The order just dropped, until the server's list (`base`) changes under it.
  const ids = workspaces.map((w) => w.id).join("\n");
  const [local, setLocal] = useState<{ base: string; order: string[] }>();
  const [drag, setDrag] = useState<Shown>();
  const press = useRef<Press | null>(null);
  // A drop is not a click: the click the browser fires right after it (if it
  // fires one at all: a finger that moved fires none) is dropped until then.
  const swallowClickUntil = useRef(0);
  const [, startSaving] = useTransition();

  const shown = useMemo(() => {
    if (!local || local.base !== ids) return workspaces;
    const byId = new Map(workspaces.map((w) => [w.id, w]));
    const placed = local.order.flatMap((id) => byId.get(id) ?? []);
    return [
      ...placed,
      ...workspaces.filter((w) => !local.order.includes(w.id)),
    ];
  }, [local, ids, workspaces]);

  const latest = useRef({ shown, ids, onDragStart });
  useLayoutEffect(() => {
    latest.current = { shown, ids, onDragStart };
  });

  const commit = useCallback((order: string[]) => {
    const base = latest.current.ids;
    setLocal({ base, order });
    startSaving(async () => {
      try {
        await saveWorkspaceOrder(order);
      } catch {
        setLocal(undefined); // not saved: back to the server's order
      }
    });
  }, []);

  // Window listeners: a pointer pressed on a tile is followed wherever it goes.
  useEffect(() => {
    const end = (drop: boolean) => {
      const p = press.current;
      press.current = null;
      if (!p) return;
      clearTimeout(p.timer);
      if (!p.active) return;
      setDrag(undefined);
      swallowClickUntil.current = performance.now() + 400;
      if (drop && p.to !== p.from)
        commit(
          moved(
            latest.current.shown.map((w) => w.id),
            p.from,
            p.to,
          ),
        );
    };
    const onMove = (event: PointerEvent) => {
      const p = press.current;
      if (!p || event.pointerId !== p.pointerId) return;
      const dy = event.clientY - p.startY;
      if (!p.active) {
        if (event.pointerType === "touch") {
          if (Math.abs(dy) > TOUCH_SLOP) end(false);
          return;
        }
        if (Math.abs(dy) < MOUSE_SLOP) return;
        p.active = true;
        latest.current.onDragStart();
      }
      p.dy = dy;
      p.to = slotAt(p, event.clientY);
      setDrag({ id: p.id, from: p.from, to: p.to, dy, slots: p.slots });
    };
    const onUp = (event: PointerEvent) => {
      if (press.current?.pointerId === event.pointerId) end(true);
    };
    const onCancel = (event: PointerEvent) => {
      if (press.current?.pointerId === event.pointerId) end(false);
    };
    // A held finger must not scroll the page under the tile.
    const onTouchMove = (event: TouchEvent) => {
      if (press.current?.active) event.preventDefault();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && press.current) end(false);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onCancel);
    window.addEventListener("touchmove", onTouchMove, { passive: false });
    window.addEventListener("keydown", onKey);
    return () => {
      clearTimeout(press.current?.timer);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onCancel);
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("keydown", onKey);
    };
  }, [commit]);

  const onPointerDown = useCallback(
    (id: string, event: ReactPointerEvent<HTMLElement>) => {
      const list = latest.current.shown;
      const ul = event.currentTarget.closest("ul");
      if (event.button !== 0 || list.length < 2 || !ul) return;
      const from = list.findIndex((w) => w.id === id);
      if (from < 0) return;
      clearTimeout(press.current?.timer);
      const p: Press = {
        id,
        from,
        to: from,
        dy: 0,
        slots: Array.from(ul.children, (li) => {
          const r = li.getBoundingClientRect();
          return r.top + r.height / 2;
        }),
        pointerId: event.pointerId,
        startY: event.clientY,
        active: false,
        timer: undefined,
      };
      if (event.pointerType === "touch")
        p.timer = setTimeout(() => {
          if (press.current !== p) return;
          p.active = true;
          latest.current.onDragStart();
          setDrag({ id, from, to: from, dy: 0, slots: p.slots });
          navigator.vibrate?.(8);
        }, TOUCH_HOLD_MS);
      press.current = p;
    },
    [],
  );

  /** On each tile (capture): a drop is not a click. */
  const onClickCapture = useCallback((event: ReactMouseEvent) => {
    if (performance.now() > swallowClickUntil.current) return;
    swallowClickUntil.current = 0;
    event.preventDefault();
    event.stopPropagation();
  }, []);

  const onKeyDown = useCallback(
    (id: string, event: ReactKeyboardEvent) => {
      if (
        !event.altKey ||
        (event.key !== "ArrowUp" && event.key !== "ArrowDown")
      )
        return;
      const list = latest.current.shown.map((w) => w.id);
      const from = list.indexOf(id);
      const to = from + (event.key === "ArrowUp" ? -1 : 1);
      if (from < 0 || to < 0 || to >= list.length) return;
      event.preventDefault();
      commit(moved(list, from, to));
    },
    [commit],
  );

  /** How far a tile is drawn from its place while one is dragged: the dragged
   * one under the pointer, the ones it passed one place over. */
  const offset = (index: number): number => {
    if (!drag) return 0;
    const { from, to, slots } = drag;
    if (index === from) return drag.dy;
    if (from < to && index > from && index <= to)
      return (slots[index - 1] ?? 0) - (slots[index] ?? 0);
    if (to < from && index >= to && index < from)
      return (slots[index + 1] ?? 0) - (slots[index] ?? 0);
    return 0;
  };

  return {
    shown,
    dragging: drag?.id ?? null,
    offset,
    onPointerDown,
    onClickCapture,
    onKeyDown,
  };
}
