"use server";

import { refresh } from "next/cache";
import type { PipelineRule } from "@/data/types";
import { core, seg } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

export type RuleFields = Pick<
  PipelineRule,
  | "name"
  | "trigger"
  | "status"
  | "goalId"
  | "label"
  | "action"
  | "member"
  | "automationId"
  | "text"
  | "enabled"
>;

const base = (workspaceId: string) =>
  `/workspaces/${seg(workspaceId)}/pipelines`;

function body(fields: RuleFields) {
  return {
    name: fields.name.trim().slice(0, 120),
    trigger: fields.trigger,
    status: fields.trigger === "status" ? fields.status : "",
    goalId: fields.goalId ?? null,
    label: fields.label.trim().replace(/^#/, "").slice(0, 40),
    action: fields.action,
    member: fields.member,
    automationId: fields.automationId ?? null,
    text: fields.text.trim().slice(0, 4000),
    enabled: fields.enabled,
  };
}

/** A new rule (null id) or a changed one; the core checks it. */
export async function savePipelineRule(
  workspaceId: string,
  ruleId: number | null,
  fields: RuleFields,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    ruleId === null
      ? core("POST", base(workspaceId), body(fields))
      : core("PUT", `${base(workspaceId)}/${seg(ruleId)}`, body(fields)),
  );
  refresh();
  return result;
}

export async function deletePipelineRule(
  workspaceId: string,
  ruleId: number,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("DELETE", `${base(workspaceId)}/${seg(ruleId)}`),
  );
  refresh();
  return result;
}
