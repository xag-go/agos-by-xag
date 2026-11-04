"use server";

import { revalidatePath } from "next/cache";
import { CoreError, core } from "@/server/core";
import { requireAccess } from "@/server/access-guard";

/** Settings → General → Labs: turn one feature flag on or off (core:
 * actions/flags.py). Owner only; the Co-Founder's `set_flag` does the same. */
export async function saveFlag(
  name: string,
  on: boolean,
): Promise<{ error: string | null }> {
  await requireAccess();
  try {
    await core("PUT", `/flags/${encodeURIComponent(name)}`, { on });
  } catch (error) {
    if (!(error instanceof CoreError)) throw error;
    return { error: error.detail };
  }
  revalidatePath("/", "layout");
  return { error: null };
}
