"use server";

import { refresh } from "next/cache";
import type { CardDocOpen, CardDocAnnotation } from "@/data/types";
import { core, CoreError, seg } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

const docs = (workspaceId: string, cardId: string) =>
  `/workspaces/${seg(workspaceId)}/kanban/${seg(cardId)}/docs`;

/** The document's text, revisions and comments (read when it is opened). */
export async function openCardDoc(
  workspaceId: string,
  cardId: string,
  key: string,
): Promise<CardDocOpen | null> {
  await requireAccess();
  try {
    return await core<CardDocOpen>(
      "GET",
      `${docs(workspaceId, cardId)}/${seg(key)}`,
    );
  } catch (error) {
    if (error instanceof CoreError && error.status === 404) return null;
    throw error;
  }
}

export type SaveDocResult = FormState & {
  revision?: number;
  /** The document moved since it was opened: reload it before saving again. */
  stale?: boolean;
};

/** A new revision; `baseRevision` is the one the editor opened (null: a new document). */
export async function saveCardDoc(
  workspaceId: string,
  cardId: string,
  key: string,
  content: string,
  why: string,
  baseRevision: number | null,
): Promise<SaveDocResult> {
  await requireAccess();
  try {
    const r = await core<{ saved: boolean; revision: number }>(
      "PUT",
      `${docs(workspaceId, cardId)}/${seg(key)}`,
      { content, why, baseRevision },
    );
    refresh();
    return { error: null, saved: r.saved, revision: r.revision };
  } catch (error) {
    if (error instanceof CoreError && error.status === 409)
      return { error: "Changed meanwhile: reload the document.", stale: true };
    if (error instanceof CoreError && error.status < 500)
      return { error: error.detail };
    throw error;
  }
}

export async function restoreCardDoc(
  workspaceId: string,
  cardId: string,
  key: string,
  revision: number,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("POST", `${docs(workspaceId, cardId)}/${seg(key)}/restore`, {
      revision,
    }),
  );
  refresh();
  return result;
}

export async function revisionText(
  workspaceId: string,
  cardId: string,
  key: string,
  revision: number,
): Promise<{ content: string; diff: string } | null> {
  await requireAccess();
  try {
    return await core<{ content: string; diff: string }>(
      "GET",
      `${docs(workspaceId, cardId)}/${seg(key)}/revisions/${String(revision)}`,
    );
  } catch {
    return null;
  }
}

export async function annotateCardDoc(
  workspaceId: string,
  cardId: string,
  key: string,
  start: number,
  end: number,
  body: string,
): Promise<FormState & { annotation?: CardDocAnnotation }> {
  await requireAccess();
  try {
    const annotation = await core<CardDocAnnotation>(
      "POST",
      `${docs(workspaceId, cardId)}/${seg(key)}/annotations`,
      { start, end, body },
    );
    refresh();
    return { error: null, saved: true, annotation };
  } catch (error) {
    if (error instanceof CoreError && error.status < 500)
      return { error: error.detail };
    throw error;
  }
}

export async function resolveAnnotation(
  workspaceId: string,
  cardId: string,
  key: string,
  annotationId: number,
  resolved: boolean,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core(
      "POST",
      `${docs(workspaceId, cardId)}/${seg(key)}/annotations/${String(annotationId)}/resolve`,
      { resolved },
    ),
  );
  refresh();
  return result;
}

export async function deleteAnnotation(
  workspaceId: string,
  cardId: string,
  key: string,
  annotationId: number,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core(
      "DELETE",
      `${docs(workspaceId, cardId)}/${seg(key)}/annotations/${String(annotationId)}`,
    ),
  );
  refresh();
  return result;
}
