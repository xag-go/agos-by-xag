"use client";

import Link from "next/link";
import { useRef, useState, type CSSProperties } from "react";
import type { ListFolder, PlanNode } from "@/data/types";
import { FolderList } from "@/features/folders/folder-list";
import { MoveToFolder, NewFolderButton } from "@/features/folders/folder-move";
import { Button, buttonClass } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { PencilIcon, PlusIcon } from "@/shared/ui/icons";
import { day, percent } from "./format";
import { Bar } from "./parts";
import { PROJECTS_MAX, cardsOf, started, type Member } from "./goal-model";
import { PROJECT_CARD, ghost } from "./goal-styles";
import { ownerName, projectShape } from "./goal-text";
import { GoalEditor } from "./goal-editor";
import {
  Avatar,
  KeyResultChip,
  Ring,
  StatusChip,
  StepPill,
} from "./goal-chips";
import { NewProject, NewResult } from "./goal-new";
import { plural } from "@/shared/format";

export function GoalCard({
  workspaceId,
  goal,
  tone,
  members,
  editing,
  onEdit,
  folders,
}: {
  workspaceId: string;
  goal: PlanNode;
  tone: number;
  members: Member[];
  editing: boolean;
  onEdit: (on: boolean) => void;
  folders: ListFolder[];
}) {
  const editButton = useRef<HTMLButtonElement>(null);
  const [adding, setAdding] = useState<"result" | "project" | null>(null);
  const [open, setOpen] = useState(false);
  const projects = goal.children ?? [];
  const results = goal.results ?? [];
  const owner = ownerName(goal.owner, members) || "Co-Founder";
  const pct = percent(goal.progress);
  const full = projects.length >= PROJECTS_MAX;
  const cards = cardsOf(goal);
  const close = () => {
    onEdit(false);
    requestAnimationFrame(() => editButton.current?.focus());
  };
  const addResult = () => {
    setAdding("result");
  };
  const addProject = () => {
    setOpen(true);
    setAdding("project");
  };
  // The "+ New project" tile fills the rest of its row (2 or 3 a row).
  const span = (cols: number, n: number) => {
    const rest = n % cols;
    return String(rest === 0 ? cols : cols - rest);
  };
  const body = `goal-body-${String(goal.id)}`;
  return (
    <article
      id={`goal-${String(goal.id)}`}
      aria-label={`Goal: ${goal.title}`}
      data-tone={tone}
      data-status={goal.status}
      className="goal-card scroll-mt-6 overflow-hidden rounded-20 bg-panel shadow-vision-card"
    >
      {editing ? (
        <div className="px-5 py-5 sm:px-6">
          <GoalEditor
            workspaceId={workspaceId}
            goal={goal}
            members={members}
            onDone={close}
          />
        </div>
      ) : (
        <div>
          <div className="goal-top px-4 pt-[18px] pb-[18px] sm:px-5">
            <div className="flex items-start gap-4">
              <div className="min-w-0 flex-1">
                <h3
                  className={cn(
                    "flex items-baseline gap-2.5 text-16.5 leading-compact font-semibold tracking-title text-balance",
                    goal.status === "active" ? "text-ink" : "text-ink-3",
                  )}
                  title={goal.why || undefined}
                >
                  <span
                    aria-hidden
                    className="size-2 shrink-0 -translate-y-0.5 rounded-full bg-goal-hue"
                  />
                  <span className="min-w-0">
                    {goal.title}
                    {goal.status !== "active" && (
                      <span className="ml-2 inline-block align-[2px]">
                        <StatusChip status={goal.status} />
                      </span>
                    )}
                  </span>
                </h3>
                <p className="mt-1 ml-[18px] flex flex-wrap items-center gap-x-2 gap-y-1 text-12.5 text-ink-3 tabular-nums">
                  <span>
                    {goal.dueOn ? `Due ${day(goal.dueOn)}` : "No due date"}
                  </span>
                  <span aria-hidden>·</span>
                  <span className="inline-flex items-center gap-1.5">
                    <Avatar name={owner} />
                    {owner}
                  </span>
                  {results.length > 0 && (
                    <>
                      <span aria-hidden>·</span>
                      <span>
                        {results.filter(started).length} of {results.length}{" "}
                        started
                      </span>
                    </>
                  )}
                </p>
              </div>
              <span className="-mt-1">
                <Ring pct={pct} />
              </span>
            </div>
            <div className="mt-3.5 flex flex-col gap-2.5">
              {results.length > 0 ? (
                <div className="goal-krs" data-n={Math.min(results.length, 6)}>
                  {results.map((k) => (
                    <KeyResultChip
                      key={k.id}
                      result={k}
                      onOpen={() => {
                        onEdit(true);
                      }}
                    />
                  ))}
                </div>
              ) : (
                adding !== "result" && (
                  <button
                    type="button"
                    className="flex min-h-11 items-center justify-center gap-2 rounded-14 border-[1.5px] border-dashed border-goal-ns text-12.5 font-semibold text-ink-2 transition-colors hover:bg-panel/50 [&_svg]:size-[13px]"
                    onClick={addResult}
                  >
                    <PlusIcon /> No numbers yet — add a key result
                  </button>
                )
              )}
              {adding === "result" && (
                <NewResult
                  workspaceId={workspaceId}
                  goalId={goal.id}
                  className="bg-panel shadow-goal"
                  onClose={() => {
                    setAdding(null);
                  }}
                />
              )}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-4 py-2 text-12.5 text-ink-3 sm:px-5">
            <span className="tabular-nums">
              <b className="font-semibold text-ink-2">
                {plural(projects.length, "project")}
              </b>
              {" · "}
              {plural(cards, "card")}
              {goal.cards.done > 0 ? ` · ${String(goal.cards.done)} done` : ""}
              {goal.cards.blocked > 0 && (
                <span className="ml-2 rounded-full bg-danger-soft px-[7px] py-px text-11 font-semibold text-danger">
                  {goal.cards.blocked} blocked
                </span>
              )}
            </span>
            <span className="ml-auto flex items-center gap-0.5">
              <Button
                ref={editButton}
                variant="ghost"
                className={ghost}
                aria-label={`Edit goal ${goal.title}`}
                onClick={() => {
                  onEdit(true);
                }}
              >
                <PencilIcon /> Edit
              </Button>
              <button
                type="button"
                className="-mr-2 inline-flex min-h-9 items-center gap-1.5 rounded-lg px-2 text-12.5 font-semibold text-accent transition-colors hover:bg-accent-soft"
                aria-expanded={open}
                aria-controls={body}
                onClick={() => {
                  setOpen(!open);
                  if (open && adding === "project") setAdding(null);
                }}
              >
                {open ? "Hide projects" : "Show projects"}
                <svg
                  aria-hidden
                  viewBox="0 0 12 12"
                  className={cn(
                    "size-3 transition-transform duration-150",
                    open && "rotate-180",
                  )}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M3 4.5 6 7.5 9 4.5" />
                </svg>
              </button>
            </span>
          </div>

          {open && (
            <div
              id={body}
              className="goal-body border-t border-line px-4 pt-3.5 pb-4 sm:px-5"
            >
              <div className="mb-3 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                <p className="text-11 font-bold tracking-caps text-ink-3 uppercase">
                  Projects · {projects.length}
                </p>
                <div className="-mr-2 flex flex-wrap items-center gap-0.5">
                  <Button
                    variant="ghost"
                    className={ghost}
                    aria-label={`Add a key result to ${goal.title}`}
                    onClick={addResult}
                  >
                    <PlusIcon /> Key result
                  </Button>
                  {!full && (
                    <Button
                      variant="ghost"
                      className={ghost}
                      aria-label={`Add a project to ${goal.title}`}
                      onClick={addProject}
                    >
                      <PlusIcon /> Project
                    </Button>
                  )}
                  <NewFolderButton
                    workspaceId={workspaceId}
                    kind="project"
                    noun="project"
                    className={buttonClass("ghost", ghost)}
                  />
                </div>
              </div>
              {adding === "project" && (
                <div className="mb-3">
                  <NewProject
                    workspaceId={workspaceId}
                    goalId={goal.id}
                    members={members}
                    onClose={() => {
                      setAdding(null);
                    }}
                  />
                </div>
              )}
              <FolderList
                workspaceId={workspaceId}
                kind="project"
                noun="project"
                variant="cards"
                folders={folders}
                toolbar={false}
                hideEmpty
                rowClassName={PROJECT_CARD}
                gridStyle={(n) =>
                  ({
                    "--goal-span-2": span(2, n),
                    "--goal-span-3": span(3, n),
                  }) as CSSProperties
                }
                entries={projects.map((p) => ({
                  id: p.id,
                  rowId: `goal-${String(p.id)}`,
                  text: `${p.title} ${p.why}`,
                  node: (
                    <ProjectCard
                      workspaceId={workspaceId}
                      project={p}
                      members={members}
                    />
                  ),
                }))}
                after={
                  !full &&
                  adding !== "project" && (
                    <li className="goal-new flex">
                      <button
                        type="button"
                        aria-label={`New project for ${goal.title}`}
                        className="flex min-h-14 w-full items-center justify-center gap-2 rounded-2xl border-[1.5px] border-dashed border-line-strong text-13 font-semibold text-ink-3 transition-colors hover:border-ink-3 hover:text-ink-2 [&_svg]:size-[15px]"
                        onClick={addProject}
                      >
                        <PlusIcon /> New project
                      </button>
                    </li>
                  )
                }
              />
            </div>
          )}
        </div>
      )}
    </article>
  );
}

function ProjectCard({
  workspaceId,
  project: p,
  members,
}: {
  workspaceId: string;
  project: PlanNode;
  members: Member[];
}) {
  const total = cardsOf(p);
  const board = `/w/${encodeURIComponent(workspaceId)}/kanban`;
  // The Kanban's goal filter (features/kanban/views.ts) keeps the project's
  // cards and its sub-items' cards: the same rollup as here.
  const href = `${board}?goal=${String(p.id)}`;
  const next = p.nextCard ?? null;
  const shape = projectShape(p) || (total === 0 ? "No cards yet" : "");
  const owner = ownerName(p.owner, members);
  return (
    <>
      <div className="flex items-start justify-between gap-2.5">
        <div className="min-w-0">
          <Link
            href={href}
            title={p.why || `Open the Kanban on ${p.title}`}
            className={cn(
              "goal-open block truncate text-sm font-semibold after:absolute after:inset-0 after:rounded-2xl after:content-['']",
              p.status === "active" ? "text-ink" : "text-ink-3",
            )}
          >
            {p.title}
          </Link>
          {(shape || p.cards.blocked > 0 || p.status !== "active") && (
            <p
              className="mt-[3px] flex min-w-0 flex-wrap items-center gap-1.5 text-xs text-ink-3"
              title={owner ? `Owner: ${owner}` : undefined}
            >
              {shape && <span className="truncate">{shape}</span>}
              {p.cards.blocked > 0 && (
                <span className="rounded-full bg-danger-soft px-[7px] py-px text-11 font-semibold whitespace-nowrap text-danger">
                  {p.cards.blocked} blocked
                </span>
              )}
              <StatusChip status={p.status} />
            </p>
          )}
        </div>
        <span className="shrink-0 text-13 font-bold text-ink-3 tabular-nums">
          {p.cards.done}/{total}
        </span>
      </div>
      <Bar pct={percent(p.progress)} thin />
      <div className="mt-auto flex min-w-0 items-center gap-2 border-t border-goal-mini-line pt-3 text-12.5 text-ink-3">
        {next ? (
          <Link
            href={`${href}&card=${encodeURIComponent(next.id)}`}
            title={`Open “${next.title}”`}
            className="relative z-10 -mx-1.5 -my-1 flex min-w-0 flex-1 items-center gap-2 rounded-lg px-1.5 py-1 transition-colors hover:bg-panel"
          >
            Next
            <b className="min-w-0 flex-1 truncate font-semibold text-ink-2">
              {next.title}
            </b>
            <StepPill status={next.status} />
          </Link>
        ) : total === 0 ? (
          <Link
            href={`${href}&new=1`}
            className="relative z-10 -mx-1.5 -my-1 flex items-center gap-1.5 rounded-lg px-1.5 py-1 font-semibold text-accent transition-colors hover:bg-panel [&_svg]:size-[13px]"
          >
            <PlusIcon /> Add first card
          </Link>
        ) : (
          <span>All cards done</span>
        )}
        <MoveToFolder
          item={p.id}
          className="relative z-10 shrink-0 [&>button]:text-12.5"
        />
      </div>
    </>
  );
}
