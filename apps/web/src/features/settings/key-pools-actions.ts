"use server";

import { refresh } from "next/cache";
import { core } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

const path = (provider: string, label?: string) =>
  `/models/key-pools/${encodeURIComponent(String(provider))}` +
  (label === undefined ? "" : `/${encodeURIComponent(String(label))}`);

/** One more key for a provider: a numbered line of Hermes's managed .env, which
 * every workspace's Hermes adds to its own credential pool. */
export async function addPoolKey(
  provider: string,
  key: string,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("POST", path(provider), { key: String(key) }),
  );
  refresh();
  return result;
}

export async function removePoolKey(
  provider: string,
  label: string,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() => core("DELETE", path(provider, label)));
  refresh();
  return result;
}

export async function movePoolKey(
  provider: string,
  label: string,
  priority: number,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", `${path(provider, label)}/priority`, {
      priority: Math.max(0, Math.round(Number(priority) || 0)),
    }),
  );
  refresh();
  return result;
}

export async function setPoolStrategy(
  provider: string,
  strategy: string,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", `${path(provider)}/strategy`, { strategy: String(strategy) }),
  );
  refresh();
  return result;
}
