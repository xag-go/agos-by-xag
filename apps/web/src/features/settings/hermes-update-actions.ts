"use server";

import { type Answer, carry } from "@/server/action";
import { core } from "@/server/core";

/** The Check Update button and the popup's "do the update" (Settings →
 * General → Hermes update; the card's poll is the GET /api/hermes-update
 * route). The core does the work (actions/hermes_update.py); these only carry
 * it to the owner's browser. */

export type HermesRelease = { version: string; sha: string };
export type HermesUpdateCheck = {
  at: string;
  current: HermesRelease;
  target: HermesRelease | null;
  fits: boolean | null;
  report: string;
  news: string[];
};
export type HermesUpdateState = {
  phase: string;
  started_at?: string;
  finished_at?: string;
  from?: HermesRelease;
  target?: HermesRelease;
  steps?: { name: string; at: string; detail?: string }[];
  error?: string | null;
  rolled_back?: boolean;
  report?: { from: string; to: string; backups: string; workspaces: number };
};
export type HermesUpdateStatus = {
  check: HermesUpdateCheck | null;
  state: HermesUpdateState | null;
};

export async function checkHermesUpdate(): Promise<Answer<HermesUpdateCheck>> {
  return carry(() => core<HermesUpdateCheck>("POST", "/hermes-update/check"));
}

export async function runHermesUpdate(): Promise<Answer<HermesUpdateState>> {
  return carry(() => core<HermesUpdateState>("POST", "/hermes-update/run"));
}
