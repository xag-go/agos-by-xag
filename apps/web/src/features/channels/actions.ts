"use server";

import { refresh } from "next/cache";
import type { BotSetup } from "@/data/types";
import { core, seg } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

function people(text: string): string[] {
  return text
    .split(/[\s,]+/)
    .map((p) => p.trim())
    .filter(Boolean)
    .slice(0, 50);
}

export async function addConnection(input: {
  kind: "telegram";
  name: string;
  secret: string;
  allowed: string;
  workspaceId?: string | null;
}): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("POST", "/channels", {
      kind: "telegram",
      name: input.name,
      secret: input.secret.trim().slice(0, 200),
      allowed: people(input.allowed),
      workspaceId: input.workspaceId ?? null,
    }),
  );
  refresh();
  return result;
}

/** Hermes's own telegram.reactions for the workspace's bot (👀 / ✅ / ❌). */
export async function setBotReactions(
  id: number,
  input: { name: string; enabled: boolean; reactions: boolean },
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", `/channels/${seg(id)}`, {
      name: input.name,
      enabled: input.enabled,
      reactions: input.reactions,
    }),
  );
  refresh();
  return result;
}

export async function deleteConnection(id: number): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() => core("DELETE", `/channels/${seg(id)}`));
  refresh();
  return result;
}

export async function addAddress(
  workspaceId: string,
  chatId: number,
  input: {
    connectionId: number;
    address: string;
    createTopicIn: string;
    notify: boolean;
  },
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core(
      "POST",
      `/workspaces/${seg(workspaceId)}/chats/${seg(chatId)}/addresses`,
      {
        connectionId: input.connectionId,
        address: input.createTopicIn
          ? null
          : input.address.trim().slice(0, 100),
        createTopicIn: input.createTopicIn.trim().slice(0, 100) || null,
        notify: input.notify,
      },
    ),
  );
  refresh();
  return result;
}

export async function removeAddress(
  workspaceId: string,
  chatId: number,
  addressId: number,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core(
      "DELETE",
      `/workspaces/${seg(workspaceId)}/chats/${seg(chatId)}/addresses/${seg(addressId)}`,
    ),
  );
  refresh();
  return result;
}

/** Starts a Telegram bot made from a QR code (the same service as Hermes). */
export async function startBotSetup(
  workspaceId: string | null,
  name: string,
): Promise<FormState & { setup?: BotSetup }> {
  await requireAccess();
  let setup: BotSetup | undefined;
  const result = await attempt(async () => {
    setup = await core<BotSetup>("POST", "/channels/telegram/setup", {
      name,
      workspaceId,
    });
  });
  return { ...result, setup };
}

/** Who may write to the bot is Hermes's: yes to a pairing request (Hermes's own). */
export async function approvePerson(
  connectionId: number,
  requestId: string,
): Promise<FormState> {
  await requireAccess();
  if (!/^[A-Za-z0-9]{1,64}$/.test(requestId)) return { error: "Not allowed" };
  const result = await attempt(() =>
    core("POST", `/channels/${seg(connectionId)}/pairing/${seg(requestId)}`),
  );
  refresh();
  return result;
}

/** The bot stops listening to this account (Hermes's pairing and allowlist). */
export async function removePerson(
  connectionId: number,
  userId: string,
): Promise<FormState> {
  await requireAccess();
  if (!/^[A-Za-z0-9_:.-]{1,100}$/.test(userId)) return { error: "Not allowed" };
  const result = await attempt(() =>
    core("DELETE", `/channels/${seg(connectionId)}/people/${seg(userId)}`),
  );
  refresh();
  return result;
}

/** The bot's t.me link: writing to it asks Hermes for a pairing code. */
export async function linkTelegramAccount(
  connectionId: number,
): Promise<FormState & { link?: string }> {
  await requireAccess();
  let link: string | undefined;
  const result = await attempt(async () => {
    ({ link } = await core<{ link: string }>(
      "POST",
      `/channels/${seg(connectionId)}/claim`,
    ));
  });
  return { ...result, link };
}

/** The workspace's team group in Telegram: each chat can get its own topic there. */
export async function setTeamGroup(
  workspaceId: string,
  group: string,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", `/workspaces/${seg(workspaceId)}/telegram-group`, {
      group: group.trim().slice(0, 30),
    }),
  );
  refresh();
  return result;
}

export type TelegramPlace = {
  address: string;
  label: string;
  group: string;
  linkedTo: string | null;
};

/** Every place in the workspace's Telegram a chat can be linked to (seen by its bot). */
export async function telegramPlaces(
  workspaceId: string,
): Promise<{ connectionId: number | null; places: TelegramPlace[] }> {
  await requireAccess();
  try {
    return await core<{ connectionId: number | null; places: TelegramPlace[] }>(
      "GET",
      `/workspaces/${seg(workspaceId)}/telegram-places`,
    );
  } catch {
    return { connectionId: null, places: [] };
  }
}
