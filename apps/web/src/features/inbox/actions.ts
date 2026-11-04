"use server";

import { refresh } from "next/cache";
import type { KanbanHold, Proposal, Question } from "@/data/types";
import { core, seg } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

export type Choice = "approve" | "revise" | "reject";

/** Approve / Revise (with a note) / Reject an agent's proposal. The core
 * answers the same decision again with the same state (idempotent). `edits`:
 * the owner's changes to a plan proposal (a key result's numbers, a project's
 * fields, a daily plan's items), applied with the approve. */
export async function decideProposal(
  workspaceId: string,
  askId: number,
  choice: Choice,
  note = "",
  edits?: Record<string, unknown>,
): Promise<FormState & { proposal?: Proposal }> {
  await requireAccess();
  let proposal: Proposal | undefined;
  const result = await attempt(async () => {
    proposal = await core<Proposal>(
      "POST",
      `/workspaces/${seg(workspaceId)}/proposals/${seg(askId)}`,
      edits && Object.keys(edits).length > 0
        ? { choice, note, payload: edits }
        : { choice, note },
    );
  });
  refresh();
  return { ...result, proposal };
}

/** Undo of an approved hire: the member goes. */
export async function undoProposal(
  workspaceId: string,
  askId: number,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core(
      "POST",
      `/workspaces/${seg(workspaceId)}/proposals/${seg(askId)}/undo`,
    ),
  );
  refresh();
  return result;
}

/** The owner's answer to a typed question, shaped by its kind (text / yes /
 * selected / verdicts / accepted, plus a note). Idempotent in the core. */
export async function answerQuestion(
  workspaceId: string,
  askId: number,
  answer: Record<string, unknown>,
): Promise<FormState & { question?: Question }> {
  await requireAccess();
  let question: Question | undefined;
  const result = await attempt(async () => {
    question = await core<Question>(
      "POST",
      `/workspaces/${seg(workspaceId)}/questions/${seg(askId)}`,
      { answer },
    );
  });
  refresh();
  return { ...result, question };
}

export type Mark = "read" | "dismissed";

/** Read (seen) or dismissed (hidden until the item changes). */
export async function markItem(
  workspaceId: string,
  key: string,
  mark: Mark,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("POST", `/workspaces/${seg(workspaceId)}/inbox/marks`, { key, mark }),
  );
  refresh();
  return result;
}

/** Undo of a read or a dismiss. */
export async function unmarkItem(
  workspaceId: string,
  key: string,
  mark: Mark,
): Promise<FormState> {
  await requireAccess();
  const q = new URLSearchParams({ key, mark });
  const result = await attempt(() =>
    core("DELETE", `/workspaces/${seg(workspaceId)}/inbox/marks?${q}`),
  );
  refresh();
  return result;
}

/** Pause / Cancel a card and everything under it (one hold in the core). */
export async function holdSubtree(
  workspaceId: string,
  cardId: string,
  action: "pause" | "cancel",
): Promise<FormState & { hold?: KanbanHold }> {
  await requireAccess();
  let hold: KanbanHold | undefined;
  const result = await attempt(async () => {
    hold = await core<KanbanHold>(
      "POST",
      `/workspaces/${seg(workspaceId)}/kanban/${seg(cardId)}/hold`,
      { action },
    );
  });
  refresh();
  return { ...result, hold };
}

/** Resume: releases exactly what the pause held and is still held. */
export async function resumeHold(
  workspaceId: string,
  holdId: number,
): Promise<FormState & { hold?: KanbanHold }> {
  await requireAccess();
  let hold: KanbanHold | undefined;
  const result = await attempt(async () => {
    hold = await core<KanbanHold>(
      "POST",
      `/workspaces/${seg(workspaceId)}/kanban/holds/${seg(holdId)}/resume`,
    );
  });
  refresh();
  return { ...result, hold };
}

type HeldRef = { profile: string; subsystem: string; ids: string[] };

/** A memory / skill change an agent wants and Hermes holds (asked once or
 * several times): Approve applies the newest copy, Reject drops them all. */
export async function decideHeld(
  workspaceId: string,
  held: HeldRef,
  approve: boolean,
): Promise<FormState & { said?: string }> {
  await requireAccess();
  let said = "";
  const result = await softly(async () => {
    ({ said } = await core<{ said: string }>(
      "POST",
      `/workspaces/${seg(workspaceId)}/held-writes/decide`,
      {
        profile: String(held.profile),
        subsystem: String(held.subsystem),
        ids: held.ids.map(String).slice(0, 50),
        approve: Boolean(approve),
      },
      120_000,
    ));
  });
  refresh();
  return { ...result, said };
}

/** Hermes's helper model on what the held change does, in plain words. */
export async function explainHeld(
  workspaceId: string,
  held: { profile: string; subsystem: string; id: string },
): Promise<{ text: string; error: string | null }> {
  await requireAccess();
  let text = "";
  const result = await softly(async () => {
    ({ text } = await core<{ text: string }>(
      "POST",
      `/workspaces/${seg(workspaceId)}/held-writes/${seg(held.profile)}/${seg(held.subsystem)}/${seg(held.id)}/explain`,
      undefined,
      150_000,
    ));
  });
  return { text, error: result.error };
}

/** Like attempt(), but Hermes's own failures (the core's 502 / 503) come back
 * as words on the card instead of an error page. */
async function softly(fn: () => Promise<unknown>): Promise<FormState> {
  const { CoreError } = await import("@/server/core");
  try {
    await fn();
    return { error: null, saved: true };
  } catch (error) {
    if (error instanceof CoreError) return { error: error.detail };
    throw error;
  }
}
