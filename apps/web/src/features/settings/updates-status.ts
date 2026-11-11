/**
 * Settings → General → Updates: what the card shows, derived from the core's
 * REAL answers (services/core actions/updates.py):
 *   GET  /updates      → { agos: {installed, current, check, state}, engine: {check, state} }
 *   POST /updates/run  → { part: "agos" | "engine", state: {...} }
 * Pure, so the node tests (scripts/updates-status.test.mjs) feed it the core's
 * own payload shapes. Owns: the one state the card shows (the running part
 * first, else the latest word, a failure never hidden). Must not: fetch.
 */

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
  /** AGOS's own part went through, the engine's part stopped: say so honestly. */
  half_done?: boolean;
};

/** One part's records, as its status() gives them (check rides along unused). */
type PartStatus = { check?: unknown; state?: UpdatesState | null } | null;

/** Core GET /updates: both parts' progress, as the two old endpoints gave it. */
export type CoreUpdatesStatus = { agos?: PartStatus; engine?: PartStatus };

/** Core POST /updates/run: which part started, and its fresh state. */
export type RunStarted = { part: "agos" | "engine"; state: UpdatesState };

export const RUNNING = [
  "queued",
  "starting",
  "backup",
  "backups",
  "stopping",
  "code",
  "hermes",
  "build",
  "sandbox",
  "gateways-off",
  "install",
  "prepare",
  "gateways-on",
  "starting-up",
  "rollback",
];

/** The one state the Updates card shows, from the core's real GET /updates:
 * a running part first (AGOS's update runs before the engine's); while nothing
 * runs, the latest word — and the engine part's failure right after AGOS's own
 * "done" is marked half_done, never hidden behind it. */
export function deriveUpdatesState(
  status: CoreUpdatesStatus,
): UpdatesState | null {
  const agos = status.agos?.state ?? null;
  const engine = status.engine?.state ?? null;
  const running = [agos, engine].find(
    (state) => state && RUNNING.includes(state.phase),
  );
  if (running) return running;
  const settled = [agos, engine].filter((state) => state !== null);
  settled.sort((a, b) => ((a.started_at ?? "") <= (b.started_at ?? "") ? -1 : 1));
  const shown = settled.at(-1) ?? null;
  if (shown && shown === engine && shown.phase === "failed" && agos?.phase === "done")
    return { ...shown, half_done: true };
  return shown;
}

/** The state to keep from Update now's answer. */
export function startedState(answer: RunStarted): UpdatesState | null {
  return answer.state ?? null;
}
