"use server";

import { refresh } from "next/cache";
import type { Rehearsal } from "@/data/types";
import { core } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

export async function setBackupPassword(password: string): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", "/backups/password", { password: password.slice(0, 200) }),
  );
  refresh();
  return result;
}

export async function setBackupSchedule(
  schedule: string,
  keep: number,
): Promise<FormState> {
  await requireAccess();
  const s = ["off", "daily", "weekly"].includes(schedule) ? schedule : "daily";
  const result = await attempt(() =>
    core("PUT", "/backups/schedule", {
      schedule: s,
      keep: Math.min(60, Math.max(1, Math.round(keep || 7))),
    }),
  );
  refresh();
  return result;
}

export async function runBackup(): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() => core("POST", "/backups/run"));
  refresh();
  return result;
}

export async function rehearseRestore(): Promise<{
  result: Rehearsal | null;
  error: string | null;
}> {
  await requireAccess();
  try {
    const result = await core<Rehearsal>("POST", "/backups/rehearse", {});
    refresh();
    return { result, error: null };
  } catch (error) {
    return {
      result: null,
      error: error instanceof Error ? error.message : "Failed",
    };
  }
}
