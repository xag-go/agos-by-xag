import type { ReactNode } from "react";

/** The amber "Waiting for you" / "Stalled" tag on a card or a row. */
export function AttentionBadge({
  children,
  title,
  shrink = false,
}: {
  children: ReactNode;
  title?: string;
  /** Keep its width in a row that squeezes its text. */
  shrink?: boolean;
}) {
  return (
    <span
      title={title}
      className={`${shrink ? "shrink-0 " : ""}rounded-md bg-attention px-1.5 py-0.5 text-xs font-medium text-attention-ink`}
    >
      {children}
    </span>
  );
}
