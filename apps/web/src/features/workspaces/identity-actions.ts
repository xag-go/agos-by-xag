"use server";

import { refresh } from "next/cache";
import { core, seg } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

const ws = (id: string) => `/workspaces/${seg(id)}`;

/** The owner's identity text for the workspace's agent (SOUL.md). */
export async function saveIdentity(
  workspaceId: string,
  text: string,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", `${ws(workspaceId)}/identity`, {
      identity: text,
    }),
  );
  refresh();
  return result;
}

/** The agent's memory ("memory") or what it knows about the owner ("user"). */
export async function saveMemory(
  workspaceId: string,
  target: "memory" | "user",
  entries: string[],
): Promise<FormState> {
  await requireAccess();
  if (target !== "memory" && target !== "user") return { error: "Not allowed" };
  const result = await attempt(() =>
    core("PUT", `${ws(workspaceId)}/memory/${target}`, {
      entries: entries.map((e) => String(e)),
    }),
  );
  refresh();
  return result;
}
