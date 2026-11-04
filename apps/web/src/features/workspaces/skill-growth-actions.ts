"use server";

import { refresh } from "next/cache";
import { core, seg } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

const base = (workspaceId: string) =>
  `/workspaces/${seg(workspaceId)}/skill-growth`;

/** How many skills the agents may ask Hermes's hub for per day (0 = none). */
export async function saveSkillRequestLimit(
  workspaceId: string,
  limit: number,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", `${base(workspaceId)}/limit`, {
      limit: Math.max(0, Math.min(20, Math.round(limit))),
    }),
  );
  refresh();
  return result;
}

/** The Co-Founder's weekly skill review job (Hermes's cron): on/off, day, time. */
export async function saveSkillReview(
  workspaceId: string,
  job: { on: boolean; time: string; day: number },
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", `${base(workspaceId)}/review`, job),
  );
  refresh();
  return result;
}
