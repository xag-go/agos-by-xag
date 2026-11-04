"use server";

import { refresh } from "next/cache";
import { CoreError, core } from "@/server/core";
import type { FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

/** One Hermes setting, written by Hermes (`hermes config set`) into every
 * workspace's Hermes, or one workspace's (AGOS keeps no copy). */
export async function saveHermesSetting(change: {
  key: string;
  value?: unknown;
  workspaceId?: string | null;
  reset?: boolean;
}): Promise<FormState> {
  await requireAccess();
  let result: FormState = { error: null, saved: true };
  try {
    await core("PUT", "/preferences/hermes-settings", {
      key: String(change.key),
      value: change.value ?? null,
      workspaceId: change.workspaceId ?? null,
      reset: Boolean(change.reset),
    });
  } catch (error) {
    // Hermes refusing it (a 502 from the core) is said on the form, like a 4xx.
    if (!(error instanceof CoreError)) throw error;
    result = { error: error.detail };
  }
  refresh();
  return result;
}
