import type { KeyboardEvent } from "react";

/** Escape closes the little form it is on. */
export function escapeTo(close: () => void) {
  return (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      close();
    }
  };
}
