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

const isRunning = (state: UpdatesState | null) =>
  state !== null && RUNNING.includes(state.phase);

const stateOf = (part?: PartStatus) => part?.state ?? null;

/** The later word of the two parts (the engine ran after AGOS when equal). */
function latestOf(
  agos: UpdatesState | null,
  engine: UpdatesState | null,
): UpdatesState | null {
  if (agos === null) return engine;
  if (engine === null) return agos;
  return (engine.started_at ?? "") < (agos.started_at ?? "") ? agos : engine;
}

/** While nothing runs: the latest word — the engine part's failure right after
 * AGOS's own "done" is marked half_done, never hidden behind it. */
function settledState(
  agos: UpdatesState | null,
  engine: UpdatesState | null,
): UpdatesState | null {
  const shown = latestOf(agos, engine);
  if (shown === engine && engine?.phase === "failed" && agos?.phase === "done")
    return { ...engine, half_done: true };
  return shown;
}

/** The one state the Updates card shows, from the core's real GET /updates:
 * a running part first (AGOS's update runs before the engine's), else the
 * settled word. */
export function deriveUpdatesState(
  status: CoreUpdatesStatus,
): UpdatesState | null {
  const agos = stateOf(status.agos);
  const engine = stateOf(status.engine);
  if (isRunning(agos)) return agos;
  if (isRunning(engine)) return engine;
  return settledState(agos, engine);
}

/** The state to keep from Update now's answer. */
export function startedState(answer: RunStarted): UpdatesState | null {
  return answer.state ?? null;
}
