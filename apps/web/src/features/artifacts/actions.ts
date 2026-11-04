"use server";

import { refresh } from "next/cache";
import { core, seg } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

const base = (workspaceId: string) =>
  `/workspaces/${seg(workspaceId)}/artifacts`;

/** The owner's review of one artifact: approved / needs work / "" (taken back). */
export async function reviewArtifact(
  workspaceId: string,
  artifact: string,
  state: "" | "approved" | "needs_work",
  note: string,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", `${base(workspaceId)}/review`, { artifact, state, note }),
  );
  refresh();
  return result;
}

/** A markdown attachment becomes a document of its card (its first revision). */
export async function promoteArtifact(
  workspaceId: string,
  card: string,
  attachment: number,
): Promise<FormState & { key?: string }> {
  await requireAccess();
  let key = "";
  const result = await attempt(async () => {
    const r = await core<{ key: string }>(
      "POST",
      `${base(workspaceId)}/promote`,
      {
        card,
        attachment,
      },
    );
    key = r.key;
  });
  refresh();
  return { ...result, key };
}
