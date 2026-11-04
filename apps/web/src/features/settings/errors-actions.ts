"use server";

import { refresh } from "next/cache";
import { core } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

/** Settings → Errors: the owner fixed it. It opens again by itself if it
 * happens again (and he is told it came back). */
export async function markErrorFixed(id: number): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("POST", `/errors/${Math.trunc(Number(id))}/fixed`),
  );
  refresh();
  return result;
}

/** Open again (the Undo of Mark fixed). */
export async function reopenError(id: number): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("POST", `/errors/${Math.trunc(Number(id))}/open`),
  );
  refresh();
  return result;
}
