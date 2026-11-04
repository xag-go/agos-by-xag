"use server";

import { refresh } from "next/cache";
import { core, seg } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

const ws = (id: string) => `/workspaces/${seg(id)}`;

export async function undoLearned(
  workspaceId: string,
  entryId: string,
): Promise<FormState> {
  await requireAccess();
  if (!/^[0-9a-f]{6,64}$/.test(entryId)) return { error: "Unknown change." };
  const result = await attempt(() =>
    core("POST", `${ws(workspaceId)}/learned/${entryId}/undo`),
  );
  refresh();
  return result;
}

export async function setAutonomy(
  workspaceId: string,
  agent: string,
  action: string,
  choice: "do" | "ask" | "never" | null,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", `${ws(workspaceId)}/autonomy`, { agent, action, choice }),
  );
  refresh();
  return result;
}

/** The apps whose answers don't count as untrusted (read vs act). [] = none. */
export async function saveTrustedApps(
  workspaceId: string,
  apps: string[],
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", `${ws(workspaceId)}/trusted-apps`, { apps }),
  );
  refresh();
  return result;
}
