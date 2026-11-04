"use server";

import { refresh } from "next/cache";
import type { NotesRevisionText, Organized } from "@/data/types";
import { CoreError, core, seg } from "@/server/core";
import { act } from "@/server/action";
import type { FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

const base = (workspaceId: string) => `/workspaces/${seg(workspaceId)}/vision`;

/** The Vision, its why and the strategy (the owner's words). */
export async function saveVision(
  workspaceId: string,
  vision: { title: string; why: string; strategy: string },
): Promise<FormState> {
  const title = vision.title.trim();
  if (!title) return { error: "Write the Vision first." };
  return act(() =>
    core("PUT", base(workspaceId), {
      title: title.slice(0, 200),
      why: vision.why.slice(0, 2000),
      strategy: vision.strategy.slice(0, 2000),
    }),
  );
}

/** A goal under the Vision. */
export async function addGoal(
  workspaceId: string,
  goal: { title: string; owner: string; dueOn: string },
): Promise<FormState> {
  const title = goal.title.trim();
  if (!title) return { error: "Give the goal a title." };
  return act(() =>
    core("POST", `${base(workspaceId)}/goals`, {
      title: title.slice(0, 200),
      owner: goal.owner,
      dueOn: goal.dueOn,
    }),
  );
}

export type ItemChanges = {
  title?: string;
  why?: string;
  owner?: string;
  status?: "active" | "paused" | "done" | "dropped";
  dueOn?: string;
  projectKind?: "dated" | "recurring";
  startsOn?: string;
  endsOn?: string;
  rhythm?: string;
};

/** A goal's or a project's fields. */
export async function changeItem(
  workspaceId: string,
  itemId: number,
  changes: ItemChanges,
): Promise<FormState> {
  return act(() =>
    core("PUT", `${base(workspaceId)}/items/${seg(itemId)}`, changes),
  );
}

/** A goal (with its projects and key results) or a project goes. */
export async function deleteItem(
  workspaceId: string,
  itemId: number,
): Promise<FormState> {
  return act(() => core("DELETE", `${base(workspaceId)}/items/${seg(itemId)}`));
}

/** A project under a goal: dated (start / end) or recurring (a rhythm). */
export async function addProject(
  workspaceId: string,
  goalId: number,
  project: {
    title: string;
    owner: string;
    projectKind: "dated" | "recurring";
    startsOn: string;
    endsOn: string;
    rhythm: string;
  },
): Promise<FormState> {
  const title = project.title.trim();
  if (!title) return { error: "Give the project a title." };
  return act(() =>
    core("POST", `${base(workspaceId)}/goals/${seg(goalId)}/projects`, {
      ...project,
      title: title.slice(0, 200),
    }),
  );
}

export type ResultFields = {
  title?: string;
  start?: number;
  current?: number;
  target?: number | null;
  unit?: string;
  dueOn?: string;
};

/** A key result of a goal: a number from its start to its target. */
export async function addResult(
  workspaceId: string,
  goalId: number,
  result: ResultFields & { title: string },
): Promise<FormState> {
  if (!result.title.trim()) return { error: "Say what is measured." };
  return act(() =>
    core("POST", `${base(workspaceId)}/goals/${seg(goalId)}/results`, result),
  );
}

/** A key result's numbers, unit, due date or title. */
export async function changeResult(
  workspaceId: string,
  resultId: number,
  changes: ResultFields,
): Promise<FormState> {
  return act(() =>
    core("PUT", `${base(workspaceId)}/results/${seg(resultId)}`, changes),
  );
}

export async function deleteResult(
  workspaceId: string,
  resultId: number,
): Promise<FormState> {
  return act(() =>
    core("DELETE", `${base(workspaceId)}/results/${seg(resultId)}`),
  );
}

/** One of the Co-Founder's daily jobs: on / off, its time (the owner's clock), its day. */
export async function setRhythm(
  workspaceId: string,
  which: "daily" | "recap" | "weekly",
  job: { on: boolean; time: string; day: number | null },
): Promise<FormState> {
  return act(() =>
    core("PUT", `${base(workspaceId)}/rhythm/${seg(which)}`, job),
  );
}

/** One of the owner's own items for today is done. */
export async function tickToday(
  workspaceId: string,
  cardId: string,
): Promise<FormState> {
  return act(() =>
    core("POST", `${base(workspaceId)}/today/${seg(cardId)}/done`),
  );
}

const NOTES_MAX = 30_000;

/** The owner's free notes (a new revision when they changed). */
export async function saveNotes(
  workspaceId: string,
  text: string,
): Promise<FormState> {
  if (text.length > NOTES_MAX)
    return { error: "Keep the notes to 30,000 characters." };
  return act(() => core("PUT", `${base(workspaceId)}/notes`, { text }));
}

/** One earlier revision of the notes (to read it or take its text back). */
export async function notesRevision(
  workspaceId: string,
  n: number,
): Promise<{ error: string | null; revision?: NotesRevisionText }> {
  await requireAccess();
  try {
    const revision = await core<NotesRevisionText>(
      "GET",
      `${base(workspaceId)}/notes/revisions/${seg(n)}`,
    );
    return { error: null, revision };
  } catch (error) {
    if (error instanceof CoreError) return { error: error.detail };
    throw error;
  }
}

/** Saves the notes, then the Co-Founder turns them into the Vision, Why and
 * Strategy (a preview: nothing saved) and proposes the goals it found in the
 * Inbox. One Hermes run: up to two minutes. */
export async function organizeNotes(
  workspaceId: string,
  text: string,
): Promise<{ error: string | null; organized?: Organized }> {
  await requireAccess();
  if (!text.trim()) return { error: "Write your notes first, then Organize." };
  if (text.length > NOTES_MAX)
    return { error: "Keep the notes to 30,000 characters." };
  try {
    await core("PUT", `${base(workspaceId)}/notes`, { text });
    const organized = await core<Organized>(
      "POST",
      `${base(workspaceId)}/notes/organize`,
      undefined,
      130_000,
    );
    refresh();
    return { error: null, organized };
  } catch (error) {
    if (error instanceof CoreError) return { error: error.detail };
    if (error instanceof Error && error.name === "TimeoutError")
      return {
        error: "The Co-Founder took too long (over two minutes). Try again.",
      };
    throw error;
  }
}
