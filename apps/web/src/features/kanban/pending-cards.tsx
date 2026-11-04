"use client";

import {
  createContext,
  use,
  useMemo,
  useOptimistic,
  type ReactNode,
} from "react";
import type { CardChange, ShownBoard } from "./optimistic";

const NONE: readonly CardChange[] = [];

type Pending = {
  /** Hermes's Kanban as the page last read it (null: Hermes didn't answer). */
  board: ShownBoard | null;
  /** The clicks whose write is still running, oldest first. */
  changes: readonly CardChange[];
  /** Shows a click at once. Call it inside the click's transition or form
   * action: React drops it by itself when that ends (W10). */
  show: (change: CardChange) => void;
};

const PendingContext = createContext<Pending>({
  board: null,
  changes: NONE,
  show: () => undefined,
});

/** Holds the Kanban's pending clicks for the Kanban and the open card, so one
 * click shows in both at once. The changes are kept apart from the Kanban and
 * laid over whatever Kanban the page has now: a live refresh that lands while a
 * write runs brings Hermes's newer Kanban and the click still shows on top of
 * it (no flicker back), and when the last click ends only Hermes's Kanban is
 * left. */
export function PendingCards({
  board,
  children,
}: {
  board: ShownBoard | null;
  children: ReactNode;
}) {
  const [changes, show] = useOptimistic(
    NONE,
    (list: readonly CardChange[], change: CardChange) => [...list, change],
  );
  const value = useMemo(
    () => ({ board, changes, show }),
    [board, changes, show],
  );
  return <PendingContext value={value}>{children}</PendingContext>;
}

export function usePendingCards(): Pending {
  return use(PendingContext);
}
