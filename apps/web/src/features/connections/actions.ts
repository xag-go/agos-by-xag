"use server";

import { refresh } from "next/cache";
import { core, seg } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

const tokenPath = (workspaceId: string) =>
  `/workspaces/${seg(workspaceId)}/mcp-token`;

/** A new MCP token for this workspace (the old one stops working). */
export async function makeMcpToken(workspaceId: string): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() => core("POST", tokenPath(workspaceId)));
  refresh();
  return result;
}

/** No outside assistant reaches this workspace any more. */
export async function removeMcpToken(workspaceId: string): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() => core("DELETE", tokenPath(workspaceId)));
  refresh();
  return result;
}
