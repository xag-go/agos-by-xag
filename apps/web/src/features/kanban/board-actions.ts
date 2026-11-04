"use server";

import { refresh } from "next/cache";
import { core, seg } from "@/server/core";
import { attempt, field, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";
import type { BoardQuery } from "./views";

// The Kanban's threads, views, labels and bulk actions (Step 58). Each is one core
// call; Hermes's own writes happen there (comments, subscriptions, the cards'
// bodies), AGOS's rows only for the labels' names and the saved views.

const ws = (workspaceId: string) => `/workspaces/${seg(workspaceId)}`;
const card = (workspaceId: string, cardId: string) =>
  `${ws(workspaceId)}/kanban/${seg(cardId)}`;

export type Woke = { who: string; title: string; how: string; said: string };
export type ThreadState = FormState & { woke?: Woke[] };

/** His comment on the card, and whom it woke (only the card's member, the
 * reviewer in Review, and the people it @mentions). */
export async function commentOnCard(
  workspaceId: string,
  cardId: string,
  _prev: ThreadState,
  form: FormData,
): Promise<ThreadState> {
  await requireAccess();
  const text = field(form, "text");
  if (!text) return { error: "Write something first." };
  let woke: Woke[] = [];
  const result = await attempt(async () => {
    const r = await core<{ woke: Woke[] }>(
      "POST",
      `${card(workspaceId, cardId)}/comment`,
      { text, resume: form.get("resume") !== null },
    );
    woke = r.woke;
  });
  refresh();
  return result.error ? result : { error: null, saved: true, woke };
}

export async function watchCard(
  workspaceId: string,
  cardId: string,
  member: string,
  on: boolean,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    on
      ? core("POST", `${card(workspaceId, cardId)}/watchers`, { member })
      : core("DELETE", `${card(workspaceId, cardId)}/watchers/${seg(member)}`),
  );
  refresh();
  return result;
}

export async function setCardLabels(
  workspaceId: string,
  cardId: string,
  ids: number[],
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", `${card(workspaceId, cardId)}/labels`, { ids }),
  );
  refresh();
  return result;
}

export type BulkAction =
  "assign" | "label" | "unblock" | "done" | "block" | "archive";

export type BulkState = FormState & {
  done?: string[];
  failed?: Record<string, string>;
};

/** One action on the selected cards, batched into Hermes by the core. */
export async function bulkCards(
  workspaceId: string,
  cards: string[],
  action: BulkAction,
  extra: {
    member?: string;
    add?: number[];
    remove?: number[];
    summary?: string;
  },
): Promise<BulkState> {
  await requireAccess();
  let out: { done: string[]; failed: Record<string, string> } = {
    done: [],
    failed: {},
  };
  const result = await attempt(async () => {
    out = await core("POST", `${ws(workspaceId)}/kanban-bulk`, {
      cards,
      action,
      ...extra,
    });
  });
  refresh();
  if (result.error) return result;
  const failed = Object.keys(out.failed);
  return {
    error: failed.length
      ? `${String(failed.length)} card${failed.length === 1 ? "" : "s"} didn't move: ${failed.join(", ")}`
      : null,
    done: out.done,
    failed: out.failed,
  };
}

/** A saved view of the Kanban (a new one, or the same id changed). */
export async function saveBoardView(
  workspaceId: string,
  name: string,
  q: BoardQuery,
  viewId: number | null,
): Promise<FormState & { id?: number }> {
  await requireAccess();
  let id = 0;
  const body = {
    name,
    filters: {
      members: q.members,
      statuses: q.statuses,
      labels: q.labels,
      goal: q.goal,
      review: q.review,
      blocked: q.blocked,
      text: q.text,
    },
    groupBy: q.groupBy,
    sort: q.sort,
    layout: q.layout,
    columns: q.columns,
  };
  const result = await attempt(async () => {
    const r = await core<{ id: number }>(
      viewId === null ? "POST" : "PUT",
      viewId === null
        ? `${ws(workspaceId)}/board-views`
        : `${ws(workspaceId)}/board-views/${String(viewId)}`,
      body,
    );
    id = r.id;
  });
  refresh();
  return result.error ? result : { error: null, saved: true, id };
}

export async function deleteBoardView(
  workspaceId: string,
  viewId: number,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("DELETE", `${ws(workspaceId)}/board-views/${String(viewId)}`),
  );
  refresh();
  return result;
}

// ---- labels (Settings → Labels) ----

export async function createLabel(
  workspaceId: string,
  _prev: FormState,
  form: FormData,
): Promise<FormState> {
  await requireAccess();
  const name = field(form, "name");
  if (!name) return { error: "Give the label a name." };
  const result = await attempt(() =>
    core("POST", `${ws(workspaceId)}/labels`, {
      name,
      color: field(form, "color") || "gray",
      folder: field(form, "folder"),
    }),
  );
  refresh();
  return result;
}

export async function updateLabel(
  workspaceId: string,
  labelId: number,
  patch: { name?: string; color?: string; folder?: string },
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", `${ws(workspaceId)}/labels/${String(labelId)}`, patch),
  );
  refresh();
  return result;
}

export async function deleteLabel(
  workspaceId: string,
  labelId: number,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("DELETE", `${ws(workspaceId)}/labels/${String(labelId)}`),
  );
  refresh();
  return result;
}

export async function renameLabelFolder(
  workspaceId: string,
  old: string,
  name: string,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("POST", `${ws(workspaceId)}/label-folders/rename`, { old, new: name }),
  );
  refresh();
  return result;
}
