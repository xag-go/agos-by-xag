import type { ReactNode } from "react";

/** The small uppercase line above a card's text ("TOOLS", "❓ … asks you"). */
export function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <p className="text-xs font-medium tracking-wide text-ink-3 uppercase">
      {children}
    </p>
  );
}
