"use server";

import { type Answer, carry } from "@/server/action";
import { core } from "@/server/core";

/** Settings → General → Updates: one Check update for everything AGOS runs on,
 * and "Update now" runs it all (AGOS first, then the engine, each with its own
 * backup, fit check and roll-back). The core does the work; these only carry it
 * to the owner's browser. The card's poll is the GET /api/updates route. */

export type UpdatesCheck = {
  ready: boolean;
  /** Something the owner should know (an install not made by the installer). */
  note?: string;
};
export type UpdatesState = {
  phase: string;
  started_at?: string;
  finished_at?: string;
  steps?: { name: string; at: string; detail?: string }[];
  error?: string | null;
  rolled_back?: boolean;
};
export type UpdatesStatus = {
  check: UpdatesCheck | null;
  state: UpdatesState | null;
};

export async function checkUpdates(): Promise<Answer<UpdatesCheck>> {
  return carry(() => core<UpdatesCheck>("POST", "/updates/check"));
}

export async function runUpdates(): Promise<Answer<UpdatesState>> {
  return carry(() => core<UpdatesState>("POST", "/updates/run"));
}
