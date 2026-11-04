"use server";

import { refresh } from "next/cache";
import type { ProviderLogin } from "@/data/types";
import { core, CoreError, seg } from "@/server/core";
import { requireAccess } from "@/server/access-guard";
import { bad, base, PROVIDERS, type Result, run } from "./provider-login-core";

/** Starts Hermes's own login for a subscription: the page to open (and code).
 * With a workspace, in that workspace's own Hermes. */
export async function startProviderLogin(
  provider: string,
  workspace?: string,
): Promise<Result> {
  await requireAccess();
  const no = bad(provider, workspace);
  if (no) return { error: no };
  return run(() =>
    core<ProviderLogin>("POST", `${base(provider, workspace)}/login`),
  );
}

export async function sendProviderLoginCode(
  provider: string,
  code: string,
  workspace?: string,
): Promise<Result> {
  await requireAccess();
  const no = bad(provider, workspace);
  if (no) return { error: no };
  const r = await run(() =>
    core<ProviderLogin>("POST", `${base(provider, workspace)}/login/code`, {
      code: code.trim().slice(0, 4000),
    }),
  );
  if (r.login?.status === "done") refresh();
  return r;
}

export async function cancelProviderLogin(
  provider: string,
  workspace?: string,
): Promise<Result> {
  await requireAccess();
  const no = bad(provider, workspace);
  if (no) return { error: no };
  return run(() =>
    core<ProviderLogin>("DELETE", `${base(provider, workspace)}/login`),
  );
}

export async function logoutProvider(
  provider: string,
  workspace?: string,
): Promise<Result> {
  await requireAccess();
  const no = bad(provider, workspace);
  if (no) return { error: no };
  const r = await run(async () => {
    await core("POST", `${base(provider, workspace)}/logout`);
    return undefined;
  });
  refresh();
  return r;
}

const KEY_PROVIDERS = PROVIDERS;

type KeyResult = { error: string | null; message?: string };

async function keyCall(
  fn: () => Promise<{ ok: boolean; message: string } | undefined>,
): Promise<KeyResult> {
  try {
    const r = await fn();
    if (r && !r.ok) return { error: r.message };
    return { error: null, message: r?.message };
  } catch (error) {
    if (error instanceof CoreError)
      return { error: error.detail || "Hermes didn't answer. Try again." };
    return { error: "AGOS didn't answer. Try again." };
  }
}

/** Tests the key with the provider; Hermes saves it only if it works. */
export async function saveApiKey(
  provider: string,
  key: string,
): Promise<KeyResult> {
  await requireAccess();
  if (!KEY_PROVIDERS.has(provider)) return { error: "Unknown provider." };
  const r = await keyCall(() =>
    core<{ ok: boolean; message: string }>(
      "PUT",
      `/models/providers/${seg(provider)}/key`,
      { key: key.trim().slice(0, 500) },
    ),
  );
  if (!r.error) refresh();
  return r;
}

export async function testApiKey(provider: string): Promise<KeyResult> {
  await requireAccess();
  if (!KEY_PROVIDERS.has(provider)) return { error: "Unknown provider." };
  const r = await keyCall(() =>
    core<{ ok: boolean; message: string }>(
      "POST",
      `/models/providers/${seg(provider)}/key/test`,
    ),
  );
  refresh();
  return r;
}

export async function removeApiKey(provider: string): Promise<KeyResult> {
  await requireAccess();
  if (!KEY_PROVIDERS.has(provider)) return { error: "Unknown provider." };
  const r = await keyCall(async () => {
    await core("DELETE", `/models/providers/${seg(provider)}/key`);
    return undefined;
  });
  refresh();
  return r;
}
