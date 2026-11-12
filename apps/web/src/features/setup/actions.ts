"use server";

import { scheduleHint } from "@agos/core";
import { refresh } from "next/cache";
import { redirect } from "next/navigation";
import { core, coreOnce, seg } from "@/server/core";
import {
  attempt,
  checked,
  field,
  modelField,
  type FormState,
} from "@/server/form";
import { requireAccess } from "@/server/access-guard";
import type { AutomationVariable, HookCondition } from "@/data/types";

function parseSteps(raw: string): unknown[] {
  if (!raw) return [];
  try {
    const value: unknown = JSON.parse(raw);
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

const base = (id: string) => `/workspaces/${seg(id)}/automations`;

const NAME = /^[a-z][a-z0-9_]*$/;

/** The Variables tab's rows (JSON): checked lightly here, for real in the core. */
function parseVariables(raw: string): AutomationVariable[] | string {
  if (!raw) return [];
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return "The variables couldn't be read.";
  }
  if (!Array.isArray(value)) return [];
  const out: AutomationVariable[] = [];
  for (const item of value as Partial<AutomationVariable>[]) {
    const name = (item.name ?? "").trim();
    if (!name) continue;
    if (!NAME.test(name))
      return `Variable “${name}”: lowercase letters, digits and _ only, starting with a letter.`;
    out.push({
      name,
      type: item.type ?? "text",
      default: item.default ?? "",
      options: (item.options ?? []).filter((o) => o.trim()),
      label: item.label ?? "",
    });
  }
  return out;
}

type AutomationBody = Record<string, unknown>;

/** What the owner must still fill in, or null when the form can be sent. */
function missingIn(form: FormData): string | null {
  if (!field(form, "name")) return "Give the automation a name.";
  if (!field(form, "instructions")) return "Write what it should do.";
  const schedule = field(form, "schedule");
  if (!schedule && field(form, "hook") !== "1")
    return "Say when it starts: a schedule, a webhook, or both.";
  // A light hint only: core checks the schedule with Hermes's own parser.
  const problem = schedule ? scheduleHint(schedule) : null;
  if (problem) return `Schedule: ${problem}.`;
  return modelField(form) ? null : "Choose a model.";
}

/** The steps: the team plan's, or a ticket preset's one step. */
function stepsOfForm(form: FormData): unknown[] {
  const steps = parseSteps(field(form, "steps"));
  if (field(form, "ticketSource") && steps.length === 0) {
    // The preset's one step: the card's standing text and who works the issues.
    return parseSteps(`[${field(form, "ticketStep")}]`);
  }
  return steps;
}

/** The form as the core takes it, or what the owner must still fill in. */
function automationBody(
  form: FormData,
): { error: string } | { body: AutomationBody } {
  const missing = missingIn(form);
  if (missing) return { error: missing };
  const variables = parseVariables(field(form, "variables"));
  if (typeof variables === "string") return { error: variables };
  const ticketSource = field(form, "ticketSource");
  return {
    body: {
      name: field(form, "name"),
      instructions: field(form, "instructions"),
      schedule: field(form, "schedule"),
      model: modelField(form),
      on: checked(form, "on"),
      agent: field(form, "agent") || null,
      steps: stepsOfForm(form),
      hook: field(form, "hook") === "1",
      checkFirst: checked(form, "checkFirst"),
      variables,
      policy: field(form, "policy") || "skip_if_active",
      catchUp: field(form, "catchUp") === "skip" ? "skip" : "once",
      ticket: ticketSource
        ? { source: ticketSource, member: field(form, "ticketMember") || null }
        : null,
    },
  };
}

export async function saveAutomation(
  workspaceId: string,
  automationId: number | null,
  _prev: FormState,
  form: FormData,
): Promise<FormState> {
  await requireAccess();
  const made = automationBody(form);
  if ("error" in made) return { error: made.error };
  const result = await attempt(() =>
    automationId === null
      ? core("POST", base(workspaceId), made.body)
      : core("PUT", `${base(workspaceId)}/${seg(automationId)}`, made.body),
  );
  if (result.error) return result;
  redirect(`/w/${workspaceId}/automations`);
}

/** What the owner's Save asks first: every problem (fix before saving), or how it
 * will run and any warnings. Nothing is saved. */
export type AutomationCheck = {
  error: string | null;
  problems: string[];
  warnings: string[];
  preview: string;
};

export async function checkAutomation(
  workspaceId: string,
  automationId: number | null,
  form: FormData,
): Promise<AutomationCheck> {
  await requireAccess();
  const none = { problems: [], warnings: [], preview: "" };
  const made = automationBody(form);
  if ("error" in made) return { error: made.error, ...none };
  const { CoreError } = await import("@/server/core");
  try {
    const found = await core<{
      problems: string[];
      warnings: string[];
      preview: string;
    }>(
      "POST",
      `${base(workspaceId)}/check${automationId === null ? "" : `?automation_id=${seg(automationId)}`}`,
      made.body,
    );
    return { error: null, ...found };
  } catch (error) {
    if (error instanceof CoreError && error.status < 500)
      return { error: error.detail, ...none };
    throw error;
  }
}

export async function toggleAutomation(
  workspaceId: string,
  automationId: number,
  on: boolean,
): Promise<void> {
  await requireAccess();
  await core("POST", `${base(workspaceId)}/${seg(automationId)}/toggle`, {
    on,
  });
  refresh();
}

export async function deleteAutomation(
  workspaceId: string,
  automationId: number,
): Promise<void> {
  await requireAccess();
  await core("DELETE", `${base(workspaceId)}/${seg(automationId)}`);
  redirect(`/w/${workspaceId}/automations`);
}

/** Fires the automation once now (within a minute), whatever its schedule;
 * `variables`: the values the manual run dialog asked (Run now with variables). */
export async function runAutomationNow(
  workspaceId: string,
  automationId: number,
  variables?: Record<string, string>,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    coreOnce(
      `${base(workspaceId)}/${seg(automationId)}/run`,
      variables && Object.keys(variables).length > 0
        ? { variables }
        : undefined,
    ),
  );
  refresh();
  return result;
}

/** Restore = a new save from revision vN (recorded as "restored from vN"). */
export async function restoreRevision(
  workspaceId: string,
  automationId: number,
  n: number,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core(
      "POST",
      `${base(workspaceId)}/${seg(automationId)}/revisions/${seg(n)}/restore`,
    ),
  );
  refresh();
  return result;
}

/** A member's heartbeat (agent "" = the Co-Founder): on with an interval, or off. */
export async function setHeartbeat(
  workspaceId: string,
  agent: string,
  on: boolean,
  interval: "15m" | "1h" | "4h" | "daily",
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core(
      "PUT",
      `/workspaces/${seg(workspaceId)}/heartbeats/${seg(agent || "cofounder")}`,
      { on, interval },
    ),
  );
  refresh();
  return result;
}

/** Watch this tree (on) / stop watching (off) on a card. */
export async function watchTree(
  workspaceId: string,
  cardId: string,
  on: boolean,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", `/workspaces/${seg(workspaceId)}/watchdogs/${seg(cardId)}`, {
      on,
    }),
  );
  refresh();
  return result;
}

/** The automation's webhook: on/off, signing secret, events, new address. A
 * signing secret AGOS made (a new webhook, or "Make a new secret") comes back
 * once, as `secret`: the dialog shows it that one time. */
export async function saveHook(
  workspaceId: string,
  automationId: number,
  body: {
    on: boolean;
    secret?: string;
    events?: string[];
    conditions?: HookCondition[];
    newAddress?: boolean;
    newSecret?: boolean;
  },
): Promise<FormState & { secret?: string }> {
  await requireAccess();
  let made: string | null | undefined;
  const result = await attempt(async () => {
    const hook = await core<{ newSecret?: string | null } | null>(
      "POST",
      `${base(workspaceId)}/${seg(automationId)}/hook`,
      body,
    );
    made = hook?.newSecret;
  });
  refresh();
  return made ? { ...result, secret: made } : result;
}

/** A signing secret AGOS made while saving the automation: shown once, here. */
export async function showHookSecret(
  workspaceId: string,
  automationId: number,
): Promise<FormState & { secret?: string }> {
  await requireAccess();
  let made: string | null | undefined;
  const result = await attempt(async () => {
    const hook = await core<{ newSecret?: string | null }>(
      "POST",
      `${base(workspaceId)}/${seg(automationId)}/hook/secret`,
    );
    made = hook.newSecret;
  });
  refresh();
  return made ? { ...result, secret: made } : result;
}

/** The public https address that reaches this machine's webhook relay. */
export async function saveHooksAddress(
  _workspaceId: string,
  _automationId: number,
  publicUrl: string,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", "/settings/hooks", { publicUrl }),
  );
  refresh();
  return result;
}

/** Stop a job an agent scheduled in the workspace's Hermes. */
export async function removeScheduled(
  workspaceId: string,
  jobId: string,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core(
      "POST",
      `/workspaces/${seg(workspaceId)}/scheduled/${seg(jobId)}/remove`,
    ),
  );
  refresh();
  return result;
}

/** Hermes's own words for a schedule as the form has it (what Hermes will save as
 * the job's schedule_display), and why it refuses it. */
export async function scheduleText(
  workspaceId: string,
  schedule: string,
): Promise<{ display: string | null; problem: string | null }> {
  await requireAccess();
  try {
    return await core<{ display: string | null; problem: string | null }>(
      "GET",
      `/workspaces/${seg(workspaceId)}/schedule-text?schedule=${encodeURIComponent(schedule)}`,
    );
  } catch {
    return { display: null, problem: null };
  }
}
