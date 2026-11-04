"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { cn } from "@/shared/ui/cn";
import { reviewChipText } from "./card-review";
import { LabelChips, type BoardLabel } from "./labels";
import type { ShownCard } from "./optimistic";
import {
  COLUMNS,
  goalAt,
  type BoardColumn,
  type BoardQuery,
  type GoalNode,
} from "./views";
import type { CardProps } from "./kanban-card";

export function ListView({
  groups,
  q,
  labels,
  goals,
  selecting,
  cardProps,
  statusLabel,
}: {
  groups: { key: string; label: string; cards: ShownCard[] }[];
  q: BoardQuery;
  labels: BoardLabel[];
  goals: GoalNode[];
  selecting: boolean;
  cardProps: (card: ShownCard) => CardProps;
  statusLabel: (s: string) => string;
}) {
  const cols: BoardColumn[] =
    q.columns.length > 0 ? q.columns : ["id", "title"];
  const head = (c: BoardColumn) =>
    COLUMNS.find((x) => x.value === c)?.label ?? c;
  const cell = (card: ShownCard, c: BoardColumn): ReactNode => {
    switch (c) {
      case "id":
        return <span className="font-mono text-xs text-ink-3">{card.id}</span>;
      case "title":
        return card.title;
      case "status":
        return statusLabel(card.status);
      case "member":
        return card.memberTitle || "Nobody yet";
      case "labels":
        return <LabelChips ids={card.labels ?? []} labels={labels} />;
      case "goal":
        return goalAt(card.goalId, "goal", goals)?.title ?? card.goalTitle;
      case "review":
        return reviewChipText(card.reviewChip);
      case "created":
        return card.createdAt
          ? new Date(card.createdAt * 1000).toLocaleDateString()
          : "";
      case "priority":
        return String(card.priority ?? 0);
    }
  };
  return (
    <div className="flex flex-col gap-4 overflow-x-auto">
      {groups.map((g) => (
        <section key={g.key || "none"}>
          <h2 className="mb-1 font-display text-sm font-semibold">
            {g.label} <span className="text-ink-3">· {g.cards.length}</span>
          </h2>
          <table className="w-full min-w-[40rem] text-left text-sm">
            <thead className="text-xs text-ink-3">
              <tr>
                {selecting && <th className="w-8" aria-label="Select" />}
                {cols.map((c) => (
                  <th key={c} className="px-2 py-1 font-medium">
                    {head(c)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {g.cards.map((card) => {
                const p = cardProps(card);
                return (
                  <tr
                    key={card.id}
                    className={cn(
                      "border-t border-line hover:bg-sunken/60",
                      p.picked && "bg-sunken",
                    )}
                  >
                    {selecting && (
                      <td className="px-2">
                        <input
                          type="checkbox"
                          aria-label={`Select ${card.id}`}
                          checked={p.picked}
                          onChange={p.onPick}
                        />
                      </td>
                    )}
                    {cols.map((c) => (
                      <td key={c} className="px-2 py-1.5">
                        {c === "title" ? (
                          <Link
                            href={p.href}
                            scroll={false}
                            className="text-ink hover:underline"
                          >
                            {card.title}
                          </Link>
                        ) : (
                          cell(card, c)
                        )}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      ))}
      {groups.every((g) => g.cards.length === 0) && (
        <p className="text-sm text-ink-3">No card fits this view.</p>
      )}
    </div>
  );
}
