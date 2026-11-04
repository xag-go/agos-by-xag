"use server";

import { core, seg } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

export type VoteKind = "reply" | "revision";

/** 👍 (1) / 👎 (-1) / none (0) on a reply or a document revision: an AGOS row,
 * said into the workspace's Hermes learning conversation (nothing leaves the server). */
export async function voteOn(
  workspaceId: string,
  kind: VoteKind,
  ref: string,
  vote: -1 | 0 | 1,
  note: string,
  subject: string,
): Promise<FormState> {
  await requireAccess();
  return attempt(() =>
    core("POST", `/workspaces/${seg(workspaceId)}/feedback`, {
      kind,
      ref,
      vote,
      note: note.slice(0, 2000),
      subject: subject.slice(0, 2000),
    }),
  );
}
