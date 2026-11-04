import type { Scorecard } from "@/data/types";
import { cn } from "@/shared/ui/cn";

/** The compact chip on a member's box: cards done this week, and a warning tone
 * when half its submissions came back from review or it has more 👎 than 👍. */
export function ScoreChip({ card }: { card?: Scorecard }) {
  if (!card || (card.cardsDone === 0 && card.submitted === 0)) return null;
  const rough =
    (card.returnRate ?? 0) >= 0.5 || card.thumbsDown > card.thumbsUp;
  return (
    <span
      title={`This week: ${String(card.cardsDone)} done${
        card.returnRate !== null && card.returnRate !== undefined
          ? `, ${String(Math.round(card.returnRate * 100))}% returned from review`
          : ""
      }`}
      className={cn(
        "mt-1 inline-flex w-fit items-center gap-1 rounded px-1 py-px text-10 font-medium tabular-nums",
        rough ? "bg-attention text-attention-ink" : "bg-sunken text-ink-2",
      )}
    >
      {card.cardsDone} done
      {card.returnRate !== null &&
        card.returnRate !== undefined &&
        ` · ${String(Math.round(card.returnRate * 100))}% back`}
    </span>
  );
}

function minutes(m: number | null | undefined): string {
  if (m === null || m === undefined) return "—";
  if (m < 60) return `${String(Math.round(m))} min`;
  const h = m / 60;
  return h < 48 ? `${h.toFixed(1)} h` : `${(h / 24).toFixed(1)} d`;
}

/** The member panel's Scorecard tab: this week, all derived from Hermes's Kanban,
 * the owner's votes and the heartbeat job (nothing stored). */
export function ScorecardPanel({
  card,
  week,
}: {
  card?: Scorecard;
  week: string;
}) {
  if (!card)
    return (
      <p className="text-sm text-ink-3">
        No scorecard for this member this week.
      </p>
    );
  const rows: [string, string][] = [
    ["Cards done", String(card.cardsDone)],
    ["Median time per card", minutes(card.medianMinutes)],
    [
      "Returned from review",
      card.returnRate === null || card.returnRate === undefined
        ? "—"
        : `${String(card.returned)} of ${String(card.submitted)} (${String(Math.round(card.returnRate * 100))}%)`,
    ],
    [
      "Times blocked",
      card.blocked === 0
        ? "0"
        : `${String(card.blocked)} · ${minutes(card.blockedMinutes)} waiting`,
    ],
    [
      "Your votes",
      `👍 ${String(card.thumbsUp)} · 👎 ${String(card.thumbsDown)}`,
    ],
    [
      "Last heartbeat",
      card.lastHeartbeat
        ? card.lastHeartbeat.slice(0, 16).replace("T", " ")
        : "None yet",
    ],
    ["Skills", String(card.skills)],
    [
      "Ready",
      card.ready === null || card.ready === undefined
        ? "—"
        : card.ready
          ? "Yes"
          : "Not yet",
    ],
  ];
  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-ink-3">Week {week}</p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-ink-3">{label}</dt>
            <dd className="text-ink tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>
      <p className="text-xs text-pretty text-ink-3">
        The Co-Founder reads these in its weekly review and proposes a fix (a
        skill, a model, access or a hire) where one looks off.
      </p>
    </div>
  );
}
