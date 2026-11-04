import type { WorkHours } from "@/data/types";
import { cn } from "@/shared/ui/cn";

export type Shift = NonNullable<
  NonNullable<WorkHours["agents"]>[number]["state"]
>;

const WORDS: Record<Shift, string> = {
  on: "On",
  off: "Off",
  staying: "Staying on today",
  finishing: "Finishing, then off",
};
// A narrow place (a Hierarchy box): the full words are its tooltip.
const SHORT: Record<Shift, string> = {
  on: "On",
  off: "Off",
  staying: "Staying on",
  finishing: "Finishing",
};

/** An agent's work hours now (Settings → Work hours): On / Off / Staying on
 * today / Finishing its card past check-out. */
export function ShiftChip({
  state,
  until,
  compact = false,
  className,
}: {
  state: Shift;
  compact?: boolean;
  /** When an off agent checks in again ("09:00", "Tue 09:00"). */
  until?: string | null;
  className?: string;
}) {
  const full = state === "off" && until ? `Off until ${until}` : WORDS[state];
  return (
    <span
      title={
        state === "off"
          ? "Off the clock: no new work, messages wait for check-in."
          : compact
            ? full
            : undefined
      }
      className={cn(
        "inline-flex shrink-0 items-center rounded px-1.5 py-px text-11 font-medium whitespace-nowrap tabular-nums",
        state === "on" && "bg-live/15 text-live",
        state === "off" && "bg-sunken text-ink-3",
        state === "staying" && "bg-accent/15 text-ink",
        state === "finishing" && "bg-attention text-attention-ink",
        className,
      )}
    >
      {compact ? SHORT[state] : full}
    </span>
  );
}
