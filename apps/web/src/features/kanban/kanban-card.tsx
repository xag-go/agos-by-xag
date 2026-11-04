"use client";

import Link from "next/link";
import { cn } from "@/shared/ui/cn";
import { reviewChipText } from "./card-review";
import { LabelChips, type BoardLabel } from "./labels";
import type { ShownCard } from "./optimistic";
import { AttentionBadge } from "@/shared/ui/attention-badge";

export type CardProps = {
  card: ShownCard;
  labels: BoardLabel[];
  href: string;
  selecting: boolean;
  picked: boolean;
  onPick: () => void;
};

export function KanbanCardView({
  card,
  labels,
  href,
  selecting,
  picked,
  onPick,
}: CardProps) {
  const asks = card.status === "blocked" && card.blockKind === "needs_input";
  // Derived from the blocker chain (the core, one read of Hermes's Kanban):
  // covered = what it waits on moves by itself; needs_attention = you must act.
  const attention = card.attention ?? "";
  const why = card.attentionWhy ?? "";
  const held = card.holdId !== null && card.holdId !== undefined;
  const review = reviewChipText(card.reviewChip);
  const className = cn(
    "task-card block w-full min-w-0 [overflow-wrap:anywhere] rounded-lg border bg-panel p-3.5 text-left shadow-card-rest transition-colors hover:border-ink-3",
    picked
      ? "border-ink ring-2 ring-ink"
      : asks
        ? "border-ink"
        : card.status === "blocked"
          ? "border-danger/50"
          : "border-line",
  );
  const body = (
    <>
      <span className="flex items-center justify-between gap-2 text-xs text-ink-3">
        <span>
          {selecting && (
            <span aria-hidden="true" className="mr-1.5">
              {picked ? "☑" : "☐"}
            </span>
          )}
          {card.id}
        </span>
        <span className="truncate">{card.memberTitle || "Nobody yet"}</span>
      </span>
      <span className="mt-2 block text-sm leading-snug font-medium [overflow-wrap:anywhere] text-ink">
        {card.title}
      </span>
      {(card.labels ?? []).length > 0 && (
        <span className="mt-2 block">
          <LabelChips ids={card.labels ?? []} labels={labels} />
        </span>
      )}
      {(asks ||
        card.status === "blocked" ||
        card.goal ||
        attention ||
        held ||
        card.goalTitle ||
        review ||
        card.chainStalled) && (
        <span className="mt-2 flex flex-wrap gap-1">
          {asks ? (
            <AttentionBadge>❓ Needs your answer</AttentionBadge>
          ) : (
            card.status === "blocked" && (
              <span className="rounded-md bg-danger-soft px-1.5 py-0.5 text-xs font-medium text-danger">
                ⚠️ Blocked
              </span>
            )
          )}
          {attention === "needs_attention" && !asks && (
            <AttentionBadge title={why}>Stalled</AttentionBadge>
          )}
          {attention === "covered" && (
            <span
              title={why}
              className="rounded-md bg-sunken px-1.5 py-0.5 text-xs text-ink-2"
            >
              Waiting · covered
            </span>
          )}
          {held && (
            <span className="rounded-md bg-sunken px-1.5 py-0.5 text-xs text-ink-2">
              ⏸ Paused
            </span>
          )}
          {card.goal && (
            <span className="rounded-md bg-sunken px-1.5 py-0.5 text-xs text-ink-2">
              Goal mode
            </span>
          )}
          {card.goalTitle && (
            <span
              title={
                card.goalInherited
                  ? "Serves this goal through its parent card"
                  : "Serves this goal"
              }
              className="max-w-full truncate rounded-md bg-sunken px-1.5 py-0.5 text-xs text-ink-2"
            >
              🎯 {card.goalTitle}
            </span>
          )}
          {review && (
            <span
              className={cn(
                "rounded-md px-1.5 py-0.5 text-xs",
                card.reviewChip?.plan === "waiting" ||
                  card.reviewChip?.phase === "stuck" ||
                  (card.reviewChip?.phase === "review" &&
                    card.status === "review")
                  ? "bg-attention font-medium text-attention-ink"
                  : "bg-sunken text-ink-2",
              )}
            >
              🔎 {review}
            </span>
          )}
          {card.chainStalled && (
            <AttentionBadge title={card.chainStalled}>
              Team stalled
            </AttentionBadge>
          )}
        </span>
      )}
      {(card.model || (card.skillPins?.length ?? 0) > 0) && (
        <span className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line pt-2.5 text-xs text-ink-3">
          {card.model && <span>{card.model}</span>}
          {(card.skillPins ?? []).map((p) => (
            <span
              key={p.skill}
              className="font-mono"
              title="Skill version loaded"
            >
              {p.skill} v{p.version}
            </span>
          ))}
        </span>
      )}
    </>
  );
  if (selecting)
    return (
      <button
        type="button"
        aria-pressed={picked}
        className={className}
        onClick={onPick}
      >
        {body}
      </button>
    );
  return (
    <Link href={href} scroll={false} className={className}>
      {body}
    </Link>
  );
}
