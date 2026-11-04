"use server";

import { refresh } from "next/cache";
import { core, seg } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

const base = (workspaceId: string) =>
  `/workspaces/${seg(workspaceId)}/tool-keys`;
const one = (workspaceId: string, name: string) =>
  `${base(workspaceId)}/${encodeURIComponent(String(name))}`;

/** The name a key for this app would be saved under (nothing is saved). */
export async function toolKeyName(
  workspaceId: string,
  app: string,
): Promise<FormState & { name?: string; url?: string; exists?: boolean }> {
  await requireAccess();
  let found: { name?: string; url?: string; exists?: boolean } = {};
  const result = await attempt(async () => {
    found = await core<{ name: string; url: string; exists: boolean }>(
      "POST",
      `${base(workspaceId)}/name`,
      { app: String(app) },
    );
  }, false);
  return { ...result, ...found };
}

/** A key for one app: Hermes keeps it in this workspace's own .env and hands it
 * to the workspace's tools. The key is sent once and never comes back. */
export async function addToolKey(
  workspaceId: string,
  app: string,
  key: string,
): Promise<FormState & { name?: string }> {
  await requireAccess();
  let name: string | undefined;
  const result = await attempt(async () => {
    const found = await core<{ savedName?: string | null }>(
      "POST",
      base(workspaceId),
      { app: String(app), key: String(key) },
    );
    name = found.savedName ?? undefined;
  });
  refresh();
  return { ...result, name };
}

export async function replaceToolKey(
  workspaceId: string,
  name: string,
  key: string,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", one(workspaceId, name), { key: String(key) }),
  );
  refresh();
  return result;
}

export async function removeToolKey(
  workspaceId: string,
  name: string,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() => core("DELETE", one(workspaceId, name)));
  refresh();
  return result;
}

export async function testToolKey(
  workspaceId: string,
  name: string,
): Promise<FormState & { ok?: boolean; message?: string }> {
  await requireAccess();
  let found: { ok?: boolean; message?: string } = {};
  const result = await attempt(async () => {
    found = await core<{ ok: boolean; message: string }>(
      "POST",
      `${one(workspaceId, name)}/test`,
    );
  }, false);
  refresh();
  return { ...result, ...found };
}
