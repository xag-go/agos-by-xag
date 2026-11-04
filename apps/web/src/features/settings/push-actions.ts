"use server";

import { refresh } from "next/cache";
import { core } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

/** The key this browser subscribes to AGOS's own notifications with. */
export async function pushKey(): Promise<string> {
  await requireAccess();
  return (await core<{ key: string }>("GET", "/push/key")).key;
}

export async function subscribePush(subscription: {
  endpoint: string;
  p256dh: string;
  auth: string;
  label: string;
}): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", "/push/subscriptions", {
      endpoint: String(subscription.endpoint).slice(0, 2000),
      p256dh: String(subscription.p256dh).slice(0, 200),
      auth: String(subscription.auth).slice(0, 100),
      label: String(subscription.label).slice(0, 120),
    }),
  );
  refresh();
  return result;
}

export async function unsubscribePush(endpoint: string): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("POST", "/push/unsubscribe", {
      endpoint: String(endpoint).slice(0, 2000),
    }),
  );
  refresh();
  return result;
}

/** Rings every subscribed device once; how many were asked. */
export async function testPush(): Promise<{
  sent: number;
  error: string | null;
}> {
  await requireAccess();
  try {
    const r = await core<{ sent: number }>("POST", "/push/test");
    return { sent: r.sent, error: null };
  } catch (e) {
    return {
      sent: 0,
      error: e instanceof Error ? e.message : "Could not send",
    };
  }
}
