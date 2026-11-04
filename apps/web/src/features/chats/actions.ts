"use server";

import { modelSelectionSchema, type ModelSelection } from "@agos/core";
import { refresh } from "next/cache";
import { redirect } from "next/navigation";
import type { ChatSearchHit } from "@/data/types";
import { core, seg } from "@/server/core";
import { attempt, field, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

const chatPath = (workspaceId: string, chatId: number) =>
  `/workspaces/${seg(workspaceId)}/chats/${seg(chatId)}`;

export async function createChat(
  workspaceId: string,
  form: FormData,
): Promise<void> {
  await requireAccess();
  const { id } = await core<{ id: number }>(
    "POST",
    `/workspaces/${seg(workspaceId)}/chats`,
    { title: field(form, "title") || "New session" },
  );
  redirect(`/w/${workspaceId}/sessions?chat=${String(id)}`);
}

export type OutgoingAttachment = {
  kind: "image" | "audio" | "file";
  name: string;
  mime: string;
  /** Base64 of the file. */
  data: string;
  duration?: number;
};

/** Saves the message (and what's attached); the agent answers in the background. */
export async function sendChatMessage(
  workspaceId: string,
  chatId: number,
  body: string,
  attachments: OutgoingAttachment[] = [],
  replyTo: number | null = null,
  replyExcerpt: string | null = null,
): Promise<FormState> {
  await requireAccess();
  const text = body.trim();
  if (!text && attachments.length === 0) return { error: null };
  if (attachments.length > 8)
    return { error: "Up to 8 attachments per message." };
  const clean = attachments.map((a) => ({
    kind: a.kind === "image" || a.kind === "audio" ? a.kind : "file",
    name: String(a.name).slice(0, 200) || "file",
    mime: String(a.mime).slice(0, 120) || "application/octet-stream",
    data: String(a.data),
    ...(typeof a.duration === "number" ? { duration: a.duration } : {}),
  }));
  const result = await attempt(() =>
    core("POST", `${chatPath(workspaceId, chatId)}/messages`, {
      body: text,
      attachments: clean,
      ...(replyTo && replyTo > 0 ? { replyTo } : {}),
      ...(replyTo && replyExcerpt
        ? { replyExcerpt: String(replyExcerpt).slice(0, 4000) }
        : {}),
    }),
  );
  refresh();
  return result;
}

/** The owner changes one of his messages. */
export async function editChatMessage(
  workspaceId: string,
  chatId: number,
  messageId: number,
  body: string,
  reanswer = false,
): Promise<FormState> {
  await requireAccess();
  const text = body.trim();
  if (!text) return { error: "A message can't be empty. Delete it instead." };
  const result = await attempt(() =>
    core(
      "PUT",
      `${chatPath(workspaceId, chatId)}/messages/${String(messageId)}`,
      { body: text, reanswer: reanswer === true },
    ),
  );
  refresh();
  return result;
}

export async function deleteChatMessage(
  workspaceId: string,
  chatId: number,
  messageId: number,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core(
      "DELETE",
      `${chatPath(workspaceId, chatId)}/messages/${String(messageId)}`,
    ),
  );
  refresh();
  return result;
}

/** "ask" before risky commands, or "full" access (inside the sandbox only). */
export async function setChatAccess(
  workspaceId: string,
  chatId: number,
  access: "ask" | "full",
): Promise<FormState> {
  await requireAccess();
  if (access !== "ask" && access !== "full") return { error: "Not allowed" };
  const result = await attempt(() =>
    core("PUT", chatPath(workspaceId, chatId), { access }),
  );
  refresh();
  return result;
}

export async function stopChat(
  workspaceId: string,
  chatId: number,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("POST", `${chatPath(workspaceId, chatId)}/stop`),
  );
  refresh();
  return result;
}

export async function retryChat(
  workspaceId: string,
  chatId: number,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("POST", `${chatPath(workspaceId, chatId)}/retry`),
  );
  refresh();
  return result;
}

/** Only "allow once" or "deny": a chat never widens what the agent may do. */
export async function answerApproval(
  workspaceId: string,
  chatId: number,
  choice: "once" | "deny",
): Promise<FormState> {
  await requireAccess();
  if (choice !== "once" && choice !== "deny") return { error: "Not allowed" };
  return attempt(() =>
    core("POST", `${chatPath(workspaceId, chatId)}/approval`, { choice }),
  );
}

/** The card of /check-simple or /check-general: suggestions? how many? */

export async function renameChat(
  workspaceId: string,
  chatId: number,
  title: string,
): Promise<FormState> {
  await requireAccess();
  const clean = title.trim();
  if (!clean) return { error: "Give the chat a name." };
  const result = await attempt(() =>
    core("PUT", chatPath(workspaceId, chatId), { title: clean }),
  );
  refresh();
  return result;
}

export async function setChatModel(
  workspaceId: string,
  chatId: number,
  model: ModelSelection,
): Promise<FormState> {
  await requireAccess();
  const parsed = modelSelectionSchema.safeParse(model);
  if (!parsed.success) return { error: "Choose a model from the list." };
  const result = await attempt(() =>
    core("PUT", chatPath(workspaceId, chatId), { model: parsed.data }),
  );
  refresh();
  return result;
}

export async function deleteChat(
  workspaceId: string,
  chatId: number,
  kind: "chat" | "dm" | "group" = "chat",
): Promise<void> {
  await requireAccess();
  await core("DELETE", chatPath(workspaceId, chatId));
  // A DM or group goes back to Workers' messages; a session to Sessions.
  redirect(
    kind === "chat"
      ? `/w/${workspaceId}/sessions`
      : `/w/${workspaceId}/messages`,
  );
}

export async function searchChats(
  workspaceId: string,
  query: string,
): Promise<ChatSearchHit[]> {
  await requireAccess();
  const q = query.trim().slice(0, 200);
  if (!q) return [];
  return core<ChatSearchHit[]>(
    "GET",
    `/workspaces/${seg(workspaceId)}/chats/search?q=${encodeURIComponent(q)}`,
  );
}

/** A library agent (on in this workspace) for this chat; "" for none. */
export async function setChatAgent(
  workspaceId: string,
  chatId: number,
  agent: string,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", chatPath(workspaceId, chatId), {
      agent: String(agent).slice(0, 63),
    }),
  );
  refresh();
  return result;
}

/** The owner's answer to the Co-Founder's request to turn a capability on/off. */
export async function decideCapability(
  workspaceId: string,
  requestId: number,
  approve: boolean,
): Promise<FormState & { loginUrl?: string | null }> {
  await requireAccess();
  const { callbackUrl } = await import("@/features/connectors/actions");
  let loginUrl: string | null | undefined;
  const result = await attempt(async () => {
    const r = await core<{ loginUrl?: string | null }>(
      "POST",
      `/workspaces/${seg(workspaceId)}/capability-requests/${seg(requestId)}`,
      { approve, redirectUri: await callbackUrl() },
    );
    loginUrl = r.loginUrl;
  });
  refresh();
  return { ...result, loginUrl };
}

/** Approve, refuse or undo something the Co-Founder did from a chat. */
export async function decideCofounderAction(
  workspaceId: string,
  actionId: number,
  choice: "approve" | "reject" | "undo",
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core(
      "POST",
      `/workspaces/${seg(workspaceId)}/cofounder-actions/${seg(actionId)}`,
      { choice },
    ),
  );
  refresh();
  return result;
}

export type HermesCommand = { command: string; description: string };

/** Hermes's command menu for a chat that lives on Hermes's Telegram (else none). */
export async function hermesCommands(
  workspaceId: string,
  chatId: number,
): Promise<HermesCommand[]> {
  await requireAccess();
  try {
    return await core<HermesCommand[]>(
      "GET",
      `${chatPath(workspaceId, chatId)}/hermes-commands`,
    );
  } catch {
    return [];
  }
}

/** Allow once / Deny what a team member working a Kanban card asks. */
export async function answerKanbanAsk(
  workspaceId: string,
  askId: number,
  allow: boolean,
): Promise<FormState & { message?: string }> {
  await requireAccess();
  let message: string | undefined;
  const result = await attempt(async () => {
    const r = await core<{ message: string }>(
      "POST",
      `/workspaces/${seg(workspaceId)}/kanban-asks/${seg(askId)}`,
      { allow },
    );
    message = r.message;
  });
  return { ...result, message };
}

/** Let it go on / Stop it, for a card using far more tokens than usual. */
export async function answerCardTokens(
  workspaceId: string,
  card: string,
  go: boolean,
): Promise<FormState & { message?: string }> {
  await requireAccess();
  let message: string | undefined;
  const result = await attempt(async () => {
    const r = await core<{ message: string }>(
      "POST",
      `/workspaces/${seg(workspaceId)}/card-tokens/${seg(card)}`,
      { go },
    );
    message = r.message;
  });
  return { ...result, message };
}
