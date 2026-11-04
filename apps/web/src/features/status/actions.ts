"use server";

import { act } from "@/server/action";
import { core, seg } from "@/server/core";
import type { FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

const base = (workspaceId: string) =>
  `/workspaces/${seg(workspaceId)}/status-cards`;

export type StatusCardFields = {
  title: string;
  scope: "workspace" | "goal" | "project" | "member" | "query";
  scopeRef: string;
  policy: "daily" | "weekly" | "manual";
  time: string;
  day: number | null;
};

function body(fields: StatusCardFields) {
  return {
    title: fields.title.trim().slice(0, 120),
    scope: fields.scope,
    scopeRef: fields.scopeRef.trim().slice(0, 200),
    policy: fields.policy,
    time: /^\d{2}:\d{2}$/.test(fields.time) ? fields.time : "08:00",
    day: fields.policy === "weekly" ? fields.day : null,
  };
}

/** A new status card (its Co-Founder job is made with it). */
export async function addStatusCard(
  workspaceId: string,
  fields: StatusCardFields,
): Promise<FormState> {
  if (!fields.title.trim()) return { error: "Give the status card a title." };
  return act(() => core("POST", base(workspaceId), body(fields)));
}

/** A card's title, scope or update policy changes (its job follows). */
export async function saveStatusCard(
  workspaceId: string,
  cardId: number,
  fields: StatusCardFields,
): Promise<FormState> {
  if (!fields.title.trim()) return { error: "Give the status card a title." };
  return act(() =>
    core("PUT", `${base(workspaceId)}/${String(cardId)}`, body(fields)),
  );
}

/** Refresh now: the Co-Founder writes a new summary within a minute or so. */
export async function refreshStatusCard(
  workspaceId: string,
  cardId: number,
): Promise<FormState> {
  return act(() =>
    core("POST", `${base(workspaceId)}/${String(cardId)}/refresh`),
  );
}

export async function deleteStatusCard(
  workspaceId: string,
  cardId: number,
): Promise<FormState> {
  return act(() => core("DELETE", `${base(workspaceId)}/${String(cardId)}`));
}

/** One revision of a card's summary, to read an older one. */
export async function statusRevision(
  workspaceId: string,
  cardId: number,
  n: number,
): Promise<{ content: string } | { error: string }> {
  await requireAccess();
  try {
    const found = await core<{ content: string }>(
      "GET",
      `${base(workspaceId)}/${String(cardId)}/revisions/${String(n)}`,
    );
    return { content: found.content };
  } catch {
    return { error: "This revision can't be read." };
  }
}
