"use client";

import Link from "next/link";
import { useState } from "react";
import type { ListFolder, PlanNode } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { PlusIcon } from "@/shared/ui/icons";
import { cardsOf, type Member } from "./goal-model";
import { NewGoal } from "./goal-new";
import { GoalCard } from "./goal-card";
import { plural } from "@/shared/format";

/**
 * Goals (owner's pick V3): one card per goal. Its header takes the goal's tint
 * (teal, amber, indigo by order): the title, due date and owner, how many key
 * results have started, the key results as chips (number, target, bar) and a
 * small ring. Its footer is one line (projects, cards, done) with Edit and
 * “Show projects”, which unfolds the project cards (next card, + New
 * project) and the + Key result / + Project actions. Edit opens that goal's
 * own form, one at a time; new key results and projects open a small form.
 */
export function GoalList({
  workspaceId,
  goals,
  members,
  editing,
  onEdit,
  folders,
}: {
  workspaceId: string;
  goals: PlanNode[];
  members: Member[];
  editing: number | null;
  onEdit: (goalId: number | null) => void;
  /** The owner's folders of the projects (AGOS's own grouping). */
  folders: ListFolder[];
}) {
  const [adding, setAdding] = useState(false);
  const inbox = `/w/${encodeURIComponent(workspaceId)}/inbox`;
  const projects = goals.flatMap((g) => g.children ?? []);
  const cardsDone = goals.reduce((n, g) => n + g.cards.done, 0);
  const cardsAll = goals.reduce((n, g) => n + cardsOf(g), 0);
  const meta = [
    plural(projects.length, "project"),
    cardsAll > 0
      ? `${String(cardsDone)} of ${plural(cardsAll, "card")} done`
      : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const add = adding ? (
    <NewGoal
      workspaceId={workspaceId}
      members={members}
      onClose={() => {
        setAdding(false);
      }}
    />
  ) : null;
  return (
    <section
      className="flex min-w-0 flex-col gap-3.5"
      aria-labelledby="goals-head"
    >
      <div className="flex min-h-9 flex-wrap items-center gap-x-2.5 gap-y-1">
        <h2
          id="goals-head"
          className="text-17 font-semibold tracking-title text-ink"
        >
          Goals
        </h2>
        {goals.length > 0 && (
          <span className="text-12.5 text-ink-3 tabular-nums">{meta}</span>
        )}
        {goals.length > 0 && !adding && (
          <Button
            className="ml-auto !h-9 gap-1.5 !rounded-10 !border-0 !px-3 font-semibold text-ink-2 !shadow-vision-card transition-[scale] active:scale-[0.96]"
            onClick={() => {
              setAdding(true);
            }}
          >
            <PlusIcon /> Add goal
          </Button>
        )}
      </div>
      {goals.length === 0 && !adding && (
        <div className="flex flex-col items-start gap-3 rounded-20 border border-dashed border-line-strong px-6 py-5">
          <p className="text-15 font-semibold text-pretty">No goals yet</p>
          <p className="max-w-prose text-sm text-pretty text-ink-2">
            Goals are the 2 to 4 things this workspace reaches in about three
            months. The Co-Founder proposes them from your Vision in your{" "}
            <Link className="underline" href={inbox}>
              Inbox
            </Link>
            , or add one yourself.
          </p>
          <Button
            variant="primary"
            onClick={() => {
              setAdding(true);
            }}
          >
            <PlusIcon /> Add goal
          </Button>
        </div>
      )}
      {add}
      {goals.map((g, i) => (
        <GoalCard
          key={g.id}
          workspaceId={workspaceId}
          goal={g}
          tone={i % 3}
          members={members}
          editing={editing === g.id}
          onEdit={(on) => {
            onEdit(on ? g.id : null);
          }}
          folders={folders}
        />
      ))}
    </section>
  );
}
