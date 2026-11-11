"use server";

import { type Answer, carry } from "@/server/action";
import { core } from "@/server/core";
import type {
  RunStarted,
  UpdatesCheck,
} from "@/features/settings/updates-status";

/** Settings → General → Updates: one Check update for everything AGOS runs on,
 * and "Update now" runs it all (AGOS first, then the engine, each with its own
 * backup, fit check and roll-back). The core does the work; these only carry it
 * to the owner's browser. The card's poll is the GET /api/updates route, and
 * the shapes the core really answers live in updates-status.ts. */

export async function checkUpdates(): Promise<Answer<UpdatesCheck>> {
  return carry(() => core<UpdatesCheck>("POST", "/updates/check"));
}

export async function runUpdates(): Promise<Answer<RunStarted>> {
  return carry(() => core<RunStarted>("POST", "/updates/run"));
}
