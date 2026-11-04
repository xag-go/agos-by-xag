"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { cn } from "@/shared/ui/cn";
import { kanbanColumns, kanbanStatusLabel } from "./kanban-columns";
import type { BoardLabel } from "./labels";
import { boardWithChanges, type ShownCard } from "./optimistic";
import { usePendingCards } from "./pending-cards";
import {
  groupCards,
  queryFrom,
  queryString,
  visibleCards,
  type BoardQuery,
  type GoalNode,
  type SavedView,
} from "./views";
import { Toolbar, type Member } from "./board-toolbar";
import { KanbanCardView, type CardProps } from "./kanban-card";
import { BulkBar } from "./bulk-bar";
import { ListView } from "./list-view";

/**
 * The workspace's Kanban (Hermes's own Kanban), in the Kanban's design: one column
 * per Hermes status, or per member / label / goal / project, or a list with the
 * columns he picks. Filters, group-by, sort and the saved views run here over the
 * Kanban's one read; the URL carries the view. Selecting cards opens the bulk bar
 * (assign, labels, move, archive: batched into Hermes by the core).
 */
export function KanbanBoardView({
  workspaceId,
  labels,
  views,
  members,
  goals,
}: {
  workspaceId: string;
  labels: BoardLabel[];
  views: SavedView[];
  members: Member[];
  goals: GoalNode[];
}) {
  const { board: hermes, changes } = usePendingCards();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const [selected, setSelected] = useState<string[]>([]);
  const [selecting, setSelecting] = useState(false);
  const q = useMemo(
    () => queryFrom(Object.fromEntries(params.entries()), views),
    [params, views],
  );
  if (hermes === null) return null;
  const board = boardWithChanges(hermes, changes);
  const columns = kanbanColumns(board.columns ?? [], board.dispatchSeconds);
  const cards = visibleCards(board.cards, q, goals);
  const groups = groupCards(cards, q.groupBy, { columns, labels, goals });
  const keep = queryString(q, views);
  const go = (next: BoardQuery) => {
    const s = queryString(next, views);
    router.replace(s ? `${pathname}?${s}` : pathname, { scroll: false });
  };
  const href = (id: string) =>
    `/w/${encodeURIComponent(workspaceId)}/kanban?${keep ? `${keep}&` : ""}card=${encodeURIComponent(id)}`;
  const cardProps = (card: ShownCard): CardProps => ({
    card,
    labels,
    href: href(card.id),
    selecting,
    picked: selected.includes(card.id),
    onPick: () => {
      setSelected((s) =>
        s.includes(card.id) ? s.filter((x) => x !== card.id) : [...s, card.id],
      );
    },
  });
  return (
    <>
      <Toolbar
        workspaceId={workspaceId}
        q={q}
        views={views}
        labels={labels}
        members={members}
        goals={goals}
        columns={columns}
        shown={cards.length}
        total={board.cards.length}
        go={go}
        selecting={selecting}
        onSelecting={(on) => {
          setSelecting(on);
          if (!on) setSelected([]);
        }}
      />
      {selecting && (
        <BulkBar
          workspaceId={workspaceId}
          selected={selected}
          all={cards.map((c) => c.id)}
          onSelect={setSelected}
          labels={labels}
          members={members}
        />
      )}
      {q.layout === "list" ? (
        <ListView
          groups={
            q.groupBy === "status"
              ? groups.filter((g) => g.cards.length > 0)
              : groups
          }
          q={q}
          labels={labels}
          goals={goals}
          selecting={selecting}
          cardProps={cardProps}
          statusLabel={(s) =>
            kanbanStatusLabel(s, columns.find((c) => c.status === s)?.label)
          }
        />
      ) : (
        <div
          data-fill
          className="task-board -mx-4 flex min-h-[24rem] flex-1 flex-col overflow-x-auto px-4 pb-1 sm:-mx-8 sm:px-8"
        >
          <ol
            className="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)] gap-3"
            style={{
              gridTemplateColumns: `repeat(${String(Math.max(groups.length, 1))}, minmax(0, 1fr))`,
              minWidth: `${String(Math.max(groups.length, 1) * 220)}px`,
            }}
          >
            {groups.map((group) => {
              const column = columns.find((c) => c.status === group.key);
              const muted = q.groupBy === "status" && group.key === "archived";
              const id = `col-${group.key || "none"}`;
              return (
                <li
                  key={group.key || "none"}
                  aria-labelledby={id}
                  className={cn(
                    "board-column flex min-h-0 min-w-0 flex-col rounded-xl bg-sunken p-2",
                    muted && "opacity-80",
                  )}
                >
                  <div className="px-1.5 pt-1 pb-3">
                    <h2
                      id={id}
                      className="flex items-center gap-2 font-display text-sm font-semibold text-ink"
                    >
                      {group.label}
                      <span className="rounded-full bg-panel px-1.5 text-xs font-medium text-ink-2">
                        {group.cards.length}
                      </span>
                    </h2>
                    {q.groupBy === "status" && (
                      <p className="mt-1 min-h-[2lh] text-xs leading-snug text-ink-3">
                        {column?.hint}
                      </p>
                    )}
                  </div>
                  <ul className="-mx-1 flex min-h-0 flex-1 flex-col gap-2 overflow-x-hidden overflow-y-auto overscroll-y-contain px-1 pt-0.5 pb-1">
                    {group.cards.map((card) => (
                      <li key={card.id} className="min-w-0">
                        <KanbanCardView {...cardProps(card)} />
                      </li>
                    ))}
                  </ul>
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </>
  );
}
