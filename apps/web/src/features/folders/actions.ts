"use server";

import { refresh } from "next/cache";
import type { FolderKind, ListFolder } from "@/data/types";
import { core, seg } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

// Folders of the Automations, Skills and Projects lists: AGOS's own grouping (the
// core's actions/folders.py). Nothing of Hermes moves; each is one core call.

const base = (workspaceId: string) =>
  `/workspaces/${seg(workspaceId)}/list-folders`;

/** A new folder (its id comes back, so a row can move into it at once). */
export async function createFolder(
  workspaceId: string,
  kind: FolderKind,
  name: string,
): Promise<FormState & { id?: number }> {
  await requireAccess();
  if (!name.trim()) return { error: "Give the folder a name." };
  let id: number | undefined;
  const result = await attempt(async () => {
    id = (await core<ListFolder>("POST", base(workspaceId), { kind, name })).id;
  });
  refresh();
  return { ...result, id };
}

export async function renameFolder(
  workspaceId: string,
  folderId: number,
  name: string,
): Promise<FormState> {
  await requireAccess();
  if (!name.trim()) return { error: "Give the folder a name." };
  const result = await attempt(() =>
    core("PUT", `${base(workspaceId)}/${String(folderId)}`, { name }),
  );
  refresh();
  return result;
}

/** The folder goes; what was in it stays, back in "No folder". */
export async function deleteFolder(
  workspaceId: string,
  folderId: number,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("DELETE", `${base(workspaceId)}/${String(folderId)}`),
  );
  refresh();
  return result;
}

/** One item into a folder (null = back to "No folder"). */
export async function moveToFolder(
  workspaceId: string,
  kind: FolderKind,
  item: number,
  folder: number | null,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("POST", `${base(workspaceId)}/move`, { kind, item, folder }),
  );
  refresh();
  return result;
}
