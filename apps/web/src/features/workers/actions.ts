"use server";

import { redirect } from "next/navigation";
import { refresh } from "next/cache";
import { core, seg } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";
import type { Readiness } from "@/data/types";

const base = (workspaceId: string) => `/workspaces/${seg(workspaceId)}/workers`;

/** Opens (or creates) the direct conversation with a member; "" = cofounder. */
export async function openDm(
  workspaceId: string,
  agent: string,
): Promise<void> {
  await requireAccess();
  const { id } = await core<{ id: number }>("POST", `${base(workspaceId)}/dm`, {
    agent: agent.slice(0, 63),
  });
  redirect(`/w/${workspaceId}/messages?c=${String(id)}`);
}

/** Who a member reports to in the org chart ("" = the Co-Founder); the core
 * refuses a loop or a name outside this workspace. */
export async function setReportsTo(
  workspaceId: string,
  agentId: number,
  reportsTo: string,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core(
      "PUT",
      `/workspaces/${seg(workspaceId)}/agents/${seg(agentId)}/reports-to`,
      { reportsTo: reportsTo.trim().slice(0, 63) },
    ),
  );
  refresh();
  return result;
}

/** The title under his name on his Founder box ("" = "Founder"). */
export async function saveFounderTitle(
  workspaceId: string,
  title: string,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", `/workspaces/${seg(workspaceId)}/founder`, {
      title: title.trim().slice(0, 64),
    }),
  );
  refresh();
  return result;
}

/** He finished one of his Founder tasks: Hermes completes its card, so the cards
 * waiting on it go on (note: what he did, optional). */
export async function finishFounderTask(
  workspaceId: string,
  card: string,
  note = "",
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("POST", `/workspaces/${seg(workspaceId)}/founder/${seg(card)}/done`, {
      note: note.trim().slice(0, 4000),
    }),
  );
  refresh();
  return result;
}

/** "Suggest hires": a card on the Co-Founder asking for the hires the team
 * needs, each its own proposal in the Inbox (the open one while an earlier ask
 * is still on the Kanban). The note goes on the card as written. */
export async function suggestHires(
  workspaceId: string,
  note: string,
): Promise<FormState & { card?: string | null; created?: boolean }> {
  await requireAccess();
  let found: { card: string | null; created: boolean } | undefined;
  const result = await attempt(async () => {
    found = await core<{ card: string | null; created: boolean }>(
      "POST",
      `/workspaces/${seg(workspaceId)}/team/suggest-hires`,
      { note: String(note) },
    );
  });
  refresh();
  return { ...result, card: found?.card, created: found?.created };
}

/** "Suggest kit": a card on the Co-Founder asking for a whole kit for a member
 * already on the team (hired before kits, or its kit misses a part). The kit
 * arrives in the Inbox as "Kit for @member" (the open card while an earlier ask,
 * or its proposal, still waits). */
export async function suggestKit(
  workspaceId: string,
  member: string,
  note = "",
): Promise<FormState & { card?: string | null; created?: boolean }> {
  await requireAccess();
  let found: { card: string | null; created: boolean } | undefined;
  const result = await attempt(async () => {
    found = await core<{ card: string | null; created: boolean }>(
      "POST",
      `${base(workspaceId)}/${seg(member)}/suggest-kit`,
      { note: String(note) },
    );
  });
  refresh();
  return { ...result, card: found?.card, created: found?.created };
}

/** "Suggest kits for all": one card per member without a whole kit, each
 * waiting on the one before so the Co-Founder takes them one at a time. */
export async function suggestKits(
  workspaceId: string,
): Promise<FormState & { asked?: number; left?: number }> {
  await requireAccess();
  let found: { asked: unknown[]; left: number } | undefined;
  const result = await attempt(async () => {
    found = await core<{ asked: unknown[]; left: number }>(
      "POST",
      `/workspaces/${seg(workspaceId)}/team/suggest-kits`,
      { note: "" },
    );
  });
  refresh();
  return { ...result, asked: found?.asked.length, left: found?.left };
}

export async function createGroup(
  workspaceId: string,
  title: string,
  members: string[],
): Promise<FormState> {
  await requireAccess();
  const name = title.trim();
  if (!name) return { error: "Give the group a name." };
  let id = 0;
  const result = await attempt(async () => {
    ({ id } = await core<{ id: number }>(
      "POST",
      `${base(workspaceId)}/groups`,
      { title: name, members },
    ));
  });
  if (result.error) return result;
  redirect(`/w/${workspaceId}/messages?c=${String(id)}`);
}

export async function setGroupMembers(
  workspaceId: string,
  chatId: number,
  members: string[],
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", `${base(workspaceId)}/groups/${seg(chatId)}/members`, {
      members,
    }),
  );
  refresh();
  return result;
}

/** A member's Readiness checklist (step 62), each item checked now; null = it
 * was hired without a kit. `check`: look again now (AGOS gives what it can, the
 * Co-Founder's card or the onboarding test follows). */
export async function readinessOf(
  workspaceId: string,
  member: string,
  check = false,
): Promise<FormState & { readiness?: Readiness | null }> {
  await requireAccess();
  let readiness: Readiness | null | undefined;
  const result = await attempt(async () => {
    readiness = await core<Readiness | null>(
      check ? "POST" : "GET",
      `${base(workspaceId)}/${seg(member)}/readiness`,
    );
  });
  return { ...result, readiness };
}

export type ReadinessChoice =
  | "not_needed"
  | "start_anyway"
  | "skip_test"
  | "retry"
  | "make_topic"
  | "clear";

/** The owner's button on one item: Not needed (with his reason), Start
 * anyway, Skip test, Retry, Make topic, or clear (undo of his choice). */
export async function chooseReadiness(
  workspaceId: string,
  member: string,
  choice: ReadinessChoice,
  item = "",
  reason = "",
): Promise<FormState & { readiness?: Readiness | null }> {
  await requireAccess();
  let readiness: Readiness | null | undefined;
  const result = await attempt(async () => {
    readiness = await core<Readiness | null>(
      "POST",
      `${base(workspaceId)}/${seg(member)}/readiness/choice`,
      { choice, item: item.slice(0, 200), reason: reason.slice(0, 2000) },
    );
  });
  refresh();
  return { ...result, readiness };
}

/** The owner's own kit for a member (his own hire, or one hired before kits). */
export async function saveKit(
  workspaceId: string,
  member: string,
  kit: Record<string, unknown>,
): Promise<FormState & { readiness?: Readiness | null }> {
  await requireAccess();
  let readiness: Readiness | null | undefined;
  const result = await attempt(async () => {
    readiness = await core<Readiness | null>(
      "PUT",
      `${base(workspaceId)}/${seg(member)}/kit`,
      { kit },
    );
  });
  refresh();
  return { ...result, readiness };
}
