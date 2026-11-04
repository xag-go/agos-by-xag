"use server";

import { refresh } from "next/cache";
import { redirect } from "next/navigation";
import type { ExternalObject } from "@/data/types";
import { core, seg } from "@/server/core";
import {
  attempt,
  checked,
  field,
  lines,
  modelField,
  type FormState,
} from "@/server/form";
import { requireAccess } from "@/server/access-guard";

const base = (workspaceId: string) => `/workspaces/${seg(workspaceId)}/kanban`;
const boardHref = (workspaceId: string) =>
  `/w/${encodeURIComponent(workspaceId)}/kanban`;

/** A new card on the workspace's Kanban (Hermes's own Kanban). */
export async function createCard(
  workspaceId: string,
  _prev: FormState,
  form: FormData,
): Promise<FormState> {
  await requireAccess();
  const title = field(form, "title");
  if (!title) return { error: "Give the card a title." };
  let id = "";
  const result = await attempt(async () => {
    const member = field(form, "member");
    const r = await core<{ id: string }>("POST", base(workspaceId), {
      title,
      body: field(form, "body"),
      member,
      criteria: lines(form, "criteria", 30),
      model: checked(form, "ownModel") ? modelField(form) : null,
      goal: checked(form, "goal"),
      parents: [...new Set(form.getAll("parents").map(String))],
      // Nobody picked: a rough idea for Hermes's Triage (it splits it for the team).
      triage: !member,
      // Workspace skills Hermes loads for the worker; their versions get pinned.
      skills: [...new Set(form.getAll("skills").map(String))].slice(0, 20),
    });
    id = r.id;
  });
  if (result.error) return result;
  redirect(`${boardHref(workspaceId)}?card=${encodeURIComponent(id)}`);
}

export async function assignCard(
  workspaceId: string,
  cardId: string,
  member: string,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("POST", `${base(workspaceId)}/${seg(cardId)}/assign`, { member }),
  );
  refresh();
  return result;
}

export async function actOnCard(
  workspaceId: string,
  cardId: string,
  action: "unblock" | "archive" | "done" | "block",
  summary?: string,
): Promise<FormState> {
  await requireAccess();
  // Mark done with his words on what was done (Hermes's completion summary, on a
  // card Hermes won't finish without them): sent as he wrote them, never made up.
  const words = summary?.trim() ?? "";
  if (summary !== undefined && !words)
    return { error: "Write what was done first." };
  const result = await attempt(() =>
    core(
      "POST",
      `${base(workspaceId)}/${seg(cardId)}/act`,
      words ? { action, summary: words } : { action },
    ),
  );
  refresh();
  return result;
}

/** His answer to a card waiting for him (❓): a comment, and the card goes on. */
export async function answerCard(
  workspaceId: string,
  cardId: string,
  _prev: FormState,
  form: FormData,
): Promise<FormState> {
  await requireAccess();
  const text = field(form, "text");
  if (!text) return { error: "Write your answer first." };
  const result = await attempt(() =>
    core("POST", `${base(workspaceId)}/${seg(cardId)}/answer`, { text }),
  );
  refresh();
  return result.error ? result : { error: null, saved: true };
}

/** The card's own chat with its member (made the first time); null if it can't be. */
export async function openCardChatId(
  workspaceId: string,
  cardId: string,
): Promise<number | null> {
  await requireAccess();
  try {
    return (
      await core<{ id: number }>(
        "POST",
        `${base(workspaceId)}/${seg(cardId)}/chat`,
      )
    ).id;
  } catch {
    return null;
  }
}

/** Hermes's own effort estimate for a card (one model call). */
export async function estimateCard(
  workspaceId: string,
  cardId: string,
): Promise<
  FormState & { estimate?: { tokens: number; complexity: string; why: string } }
> {
  await requireAccess();
  let estimate: { tokens: number; complexity: string; why: string } | undefined;
  const result = await attempt(async () => {
    estimate = await core<{ tokens: number; complexity: string; why: string }>(
      "POST",
      `${base(workspaceId)}/${seg(cardId)}/estimate`,
    );
  });
  return { ...result, estimate };
}

/** A file he adds to a card (Hermes's own attachment). */
export async function attachToCard(
  workspaceId: string,
  cardId: string,
  name: string,
  data: string,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("POST", `${base(workspaceId)}/${seg(cardId)}/attachments`, {
      name,
      data,
    }),
  );
  refresh();
  return result;
}

export async function removeCardFile(
  workspaceId: string,
  cardId: string,
  fileId: number,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core(
      "DELETE",
      `${base(workspaceId)}/${seg(cardId)}/attachments/${seg(fileId)}`,
    ),
  );
  refresh();
  return result;
}

/** The sub-goal the card serves (null: none): its Hermes body's '## Goal'
 * section, which the agent working it reads. */
export async function setCardGoal(
  workspaceId: string,
  cardId: string,
  goalId: number | null,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", `${base(workspaceId)}/${seg(cardId)}/goal`, { goalId }),
  );
  refresh();
  return result;
}

/** His decision on a card's review (its stage or plan waiting, or stuck): approve,
 * changes (with a note), reassign (to `member`) or drop. */
export async function decideReview(
  workspaceId: string,
  cardId: string,
  action: "approve" | "changes" | "reassign" | "drop",
  note = "",
  member = "",
): Promise<FormState> {
  await requireAccess();
  if (action === "changes" && !note.trim())
    return { error: "Write what to change first." };
  const result = await attempt(() =>
    core("POST", `${base(workspaceId)}/${seg(cardId)}/review`, {
      action,
      note: note.trim(),
      member,
    }),
  );
  refresh();
  return result;
}

/** The card's own review rules (its body's block); `reset` = the workspace's. */
export async function setReviewRules(
  workspaceId: string,
  cardId: string,
  rules: {
    stages?: string[];
    cap?: number;
    plan?: boolean;
    planReviewer?: string;
    reset?: boolean;
  },
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", `${base(workspaceId)}/${seg(cardId)}/review`, rules),
  );
  refresh();
  return result;
}

/** The workspace's review defaults (Settings → Review). */
export async function saveReviewSettings(
  workspaceId: string,
  settings: {
    stages: string[];
    cap: number;
    planFirst: boolean;
    planReviewer: string;
  },
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", `/workspaces/${seg(workspaceId)}/review-settings`, settings),
  );
  refresh();
  return result;
}

/** Live chips for the outside objects a card's text links (PRs, issues,
 * tickets): read by the core with the workspace's own keys, kept briefly. */
export async function resolveLinks(
  workspaceId: string,
  urls: string[],
): Promise<ExternalObject[]> {
  await requireAccess();
  const wanted = [...new Set(urls)].slice(0, 20).map((u) => u.slice(0, 500));
  if (wanted.length === 0) return [];
  return core<ExternalObject[]>(
    "POST",
    `/workspaces/${seg(workspaceId)}/external-objects`,
    { urls: wanted },
  ).catch(() => []);
}

/** Stop a dev server / preview the card's worker started. */
export async function stopCardService(
  workspaceId: string,
  serviceId: number,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core(
      "POST",
      `/workspaces/${seg(workspaceId)}/services/${seg(serviceId)}/stop`,
    ),
  );
  refresh();
  return result;
}
