"use server";

import { type Answer, carry } from "@/server/action";
import { core } from "@/server/core";

/** Settings → General → Update AGOS: Check Update and "Update now" (the same
 * update as `agos update` on the machine; core: actions/agos_update.py). The
 * card's poll is the GET /api/agos-update route. Owner only. */

export type AgosUpdateCheck = {
  at: string;
  ref: string;
  current: string;
  target: string | null;
  /** The new release's version (its VERSION file); "" for an older release. */
  target_version?: string;
  news: string[];
  hermes_changes: boolean;
};
export type AgosUpdateState = {
  phase: string;
  started_at?: string;
  finished_at?: string;
  from?: string;
  to?: string;
  steps?: { name: string; at: string; detail?: string }[];
  error?: string | null;
  rolled_back?: boolean;
};
export type AgosUpdateStatus = {
  installed: boolean;
  current: { version?: string; sha: string; date: string };
  check: AgosUpdateCheck | null;
  state: AgosUpdateState | null;
};

export async function checkAgosUpdate(): Promise<Answer<AgosUpdateCheck>> {
  return carry(() => core<AgosUpdateCheck>("POST", "/agos-update/check"));
}

export async function runAgosUpdate(): Promise<Answer<AgosUpdateState>> {
  return carry(() => core<AgosUpdateState>("POST", "/agos-update/run"));
}
