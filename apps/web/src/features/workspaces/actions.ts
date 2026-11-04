"use server";

import { refresh } from "next/cache";
import { redirect } from "next/navigation";
import type { BotRestart, FolderListing, Workspace } from "@/data/types";
import { core, coreOnce, coreUpload, seg } from "@/server/core";
import {
  attempt,
  checked,
  field,
  modelField,
  type FormState,
} from "@/server/form";
import { requireAccess } from "@/server/access-guard";

const ws = (id: string) => `/workspaces/${seg(id)}`;

export async function createWorkspace(
  _prev: FormState,
  form: FormData,
): Promise<FormState> {
  await requireAccess();
  const name = field(form, "name");
  const model = modelField(form);
  if (!name) return { error: "Give the workspace a name." };
  if (!model) return { error: "Choose a default model." };
  let id = "";
  const result = await attempt(async () => {
    ({ id } = await coreOnce<{ id: string }>("/workspaces", {
      name,
      description: field(form, "description"),
      defaultModel: model,
    }));
  });
  if (result.error) return result;
  redirect(
    checked(form, "telegramBot")
      ? `/w/${id}/settings/channels?setup=qr`
      : `/w/${id}/kanban`,
  );
}

export async function saveWorkspaceSettings(
  workspaceId: string,
  _prev: FormState,
  form: FormData,
): Promise<FormState> {
  await requireAccess();
  const model = modelField(form);
  if (!field(form, "name")) return { error: "The name can't be empty." };
  if (!model) return { error: "Choose a default model." };
  const result = await attempt(async () => {
    // Agent access is set on its own (instantly) further down the page; keep it.
    const current = await core<Workspace>("GET", ws(workspaceId));
    await core("PUT", ws(workspaceId), {
      name: field(form, "name"),
      description: field(form, "description"),
      defaultModel: model,
      chatAccess: current.chatAccess,
    });
  });
  if (result.error) return result;
  // Hermes's own settings go to the workspace's Hermes (AGOS keeps no copy).
  const values: Record<string, string> = {};
  for (const [name, value] of form.entries()) {
    if (name.startsWith("hermes:") && typeof value === "string")
      values[name.slice("hermes:".length)] = value.trim();
  }
  const hermes = Object.keys(values).length
    ? await attempt(() =>
        core("PUT", `${ws(workspaceId)}/hermes-settings`, { values }),
      )
    : result;
  refresh();
  return hermes.error ? hermes : result;
}

/** The picture on the workspace's tile (PNG, JPEG, WebP or SVG, up to 1 MB):
 * the file goes to the core as it is, which reads its type from the bytes. */
export async function uploadWorkspaceIcon(
  workspaceId: string,
  form: FormData,
): Promise<FormState> {
  await requireAccess();
  const file = form.get("icon");
  if (!(file instanceof Blob) || file.size === 0)
    return { error: "Choose a picture first." };
  const result = await attempt(() =>
    coreUpload("PUT", `${ws(workspaceId)}/icon`, file),
  );
  refresh();
  return result;
}

export async function removeWorkspaceIcon(
  workspaceId: string,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() => core("DELETE", `${ws(workspaceId)}/icon`));
  refresh();
  return result;
}

/** Agent access for the whole workspace, saved the moment it is picked. */
export async function setWorkspaceAccess(
  workspaceId: string,
  access: "ask" | "full",
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(async () => {
    const current = await core<Workspace>("GET", ws(workspaceId));
    await core("PUT", ws(workspaceId), {
      name: current.name,
      description: current.description,
      defaultModel: current.defaultModel,
      chatAccess: access === "full" ? "full" : "ask",
    });
  });
  refresh();
  return result;
}

/** Hermes's own deny and allow rules (approvals.deny, command_allowlist),
 * written into the workspace's Co-Founder and each member. */
export async function saveAccessLists(
  workspaceId: string,
  lists: { deny: string[]; allow: string[] },
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(async () => {
    await core("PUT", `${ws(workspaceId)}/access-lists`, {
      deny: lists.deny.map(String),
      allow: lists.allow.map(String),
    });
  });
  refresh();
  return result;
}

export async function addFolder(
  workspaceId: string,
  _prev: FormState,
  form: FormData,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("POST", `${ws(workspaceId)}/folders`, {
      path: field(form, "path"),
      access: field(form, "access") === "read-write" ? "read-write" : "read",
    }),
  );
  refresh();
  return result;
}

export async function setFolderAccess(
  workspaceId: string,
  name: string,
  form: FormData,
): Promise<void> {
  await requireAccess();
  await core("PUT", `${ws(workspaceId)}/folders/${seg(name)}`, {
    access: field(form, "access") === "read-write" ? "read-write" : "read",
  });
  refresh();
}

export async function removeFolder(
  workspaceId: string,
  name: string,
): Promise<void> {
  await requireAccess();
  await core("DELETE", `${ws(workspaceId)}/folders/${seg(name)}`);
  refresh();
}

/** The gateway restart a folder click starts after its answer: restarting,
 * done, or failed with the reason (the agent is then stopped). */
export async function botRestart(workspaceId: string): Promise<BotRestart> {
  await requireAccess();
  return core<BotRestart>("GET", `${ws(workspaceId)}/gateway-restart`);
}

export async function archiveWorkspace(workspaceId: string): Promise<void> {
  await requireAccess();
  await core("POST", `${ws(workspaceId)}/archive`);
  redirect("/");
}

export async function unarchiveWorkspace(workspaceId: string): Promise<void> {
  await requireAccess();
  await core("POST", `${ws(workspaceId)}/unarchive`);
  refresh();
}

export async function deleteWorkspace(
  workspaceId: string,
  _prev: FormState,
  form: FormData,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("POST", `${ws(workspaceId)}/delete`, {
      confirm: field(form, "confirm"),
    }),
  );
  if (result.error) return result;
  redirect("/");
}

export async function restoreWorkspace(workspaceId: string): Promise<void> {
  await requireAccess();
  await core("POST", `/trash/${seg(workspaceId)}/restore`);
  refresh();
}

export async function purgeWorkspace(workspaceId: string): Promise<void> {
  await requireAccess();
  await core("DELETE", `/trash/${seg(workspaceId)}`);
  refresh();
}

/** This machine's folders (names only), for the folder picker. */
export async function browseFolders(
  path: string | null,
): Promise<FormState & { listing?: FolderListing }> {
  await requireAccess();
  let listing: FolderListing | undefined;
  const q = path ? `?path=${encodeURIComponent(path.slice(0, 1000))}` : "";
  const result = await attempt(async () => {
    listing = await core<FolderListing>("GET", `/machine/folders${q}`);
  });
  return { ...result, listing };
}
