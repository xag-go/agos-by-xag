"use server";

import { refresh } from "next/cache";
import type { DaySpan } from "@/data/types";
import { core, seg } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

const base = (workspaceId: string) =>
  `/workspaces/${seg(workspaceId)}/work-hours`;

/** Settings → Work hours: on/off and each day's range (null = OFF). */
export async function saveWorkHours(
  workspaceId: string,
  hours: { on: boolean; days: Record<string, DaySpan | null> },
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() => core("PUT", base(workspaceId), hours));
  refresh();
  return result;
}

/** Who stays on today: these agents ("" = the Co-Founder) work until the next
 * check-in, then the pick clears by itself. */
export async function setStayOnToday(
  workspaceId: string,
  agents: string[],
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", `${base(workspaceId)}/stay`, { agents: agents.slice(0, 50) }),
  );
  refresh();
  return result;
}

/** Wake now (a chat's off line): the agent is on for today. */
export async function wakeNow(
  workspaceId: string,
  agent: string,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("POST", `${base(workspaceId)}/wake`, { agent }),
  );
  refresh();
  return result;
}
