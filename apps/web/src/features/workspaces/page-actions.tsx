"use client";

import { useSyncExternalStore, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { PAGE_ACTIONS_SLOT } from "./workspace-title";

const noop = () => () => {};

/** A page's own buttons, shown at the right of the page title. */
export function PageActions({ children }: { children: ReactNode }) {
  // The slot exists only in the browser; on the server there is nothing to fill.
  const slot = useSyncExternalStore(
    noop,
    () => document.getElementById(PAGE_ACTIONS_SLOT),
    () => null,
  );
  return slot ? createPortal(children, slot) : null;
}
