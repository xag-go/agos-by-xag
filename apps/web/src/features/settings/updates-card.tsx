"use client";

import { useEffect, useEffectEvent, useRef, useState } from "react";
import { getStatus } from "@/shared/get-status";
import { Button } from "@/shared/ui/button";
import { checkUpdates, runUpdates } from "./updates-actions";
import {
  type CoreUpdatesStatus,
  deriveUpdatesState,
  RUNNING,
  startedState,
  type UpdatesCheck,
  type UpdatesState,
} from "./updates-status";

/**
 * Settings → General → Updates: one Check update for everything AGOS runs on
 * (docs/specs/2026-11-04-no-engine-name.md). "Update now" runs it all: backups
 * first, AGOS stops for a few minutes and comes back by itself — on the old
 * release if anything fails. The core does the work and names each step; this
 * card never says which part updates.
 */

const STEP_WORDS: Record<string, string> = {
  queued: "Starting…",
  starting: "Starting…",
  backup: "Backing everything up",
  backups: "Backing everything up",
  stopping: "Pausing AGOS",
  code: "Getting the new release",
  hermes: "Updating the engine",
  build: "Building the new release",
  sandbox: "Rebuilding the workspace sandbox",
  "gateways-off": "Pausing the workspaces",
  install: "Installing the new engine",
  prepare: "Preparing every workspace",
  "gateways-on": "Waking the workspaces",
  "starting-up": "Starting AGOS again",
  rollback: "Something failed: putting the old release back",
};

/** Polls the card's GET status route while `watching` asks for it: `onAnswer` gets each
 * answer (null = no answer) and returns the wait before the next read, or null to stop. */
function useUpdatePoll<T>(
  url: string,
  watching: number,
  onAnswer: (data: T | null) => number | null,
) {
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const answered = useEffectEvent(onAnswer);
  useEffect(() => {
    let stopped = false;
    const read = async () => {
      const answer = await getStatus<
        { ok: true; data: T } | { ok: false; error: string }
      >(url);
      if (stopped) return;
      const wait = answered(answer?.ok ? answer.data : null);
      if (wait !== null) timer.current = setTimeout(() => void read(), wait);
    };
    void read();
    return () => {
      stopped = true;
      clearTimeout(timer.current);
    };
  }, [url, watching]);
}

/** Polls the status route while an update runs; `away` while AGOS restarts.
 * The core answers both parts' records (see updates-status.ts); the card shows
 * the one state derived from them. */
function useUpdatesStatus(
  watching: number,
  setState: (state: UpdatesState) => void,
  setAway: (away: boolean) => void,
) {
  useUpdatePoll<CoreUpdatesStatus>("/api/updates", watching, (data) => {
    if (!data) {
      // AGOS restarts during an update: keep asking until it is back.
      if (watching === 0) return null;
      setAway(true);
      return 4000;
    }
    setAway(false);
    const state = deriveUpdatesState(data);
    if (state) setState(state);
    return state && RUNNING.includes(state.phase) ? 3000 : null;
  });
}

/** The live step list while the update runs (or while AGOS restarts). */
function Progress({
  state,
  away,
}: {
  state: UpdatesState | null;
  away: boolean;
}) {
  return (
    <div
      aria-live="polite"
      className="rounded-xl border border-line bg-panel-2 p-4"
    >
      <p className="text-sm font-medium">
        AGOS is updating — it stops for a few minutes and this page comes back
        by itself…
      </p>
      <ol className="mt-2 flex flex-col gap-1 text-sm text-ink-2">
        {(state?.steps ?? []).map((step) => (
          <li key={`${step.name}-${step.at}`}>
            {!away && step.name === state?.phase ? "⏳" : "✓"}{" "}
            {STEP_WORDS[step.name] ?? step.name}
          </li>
        ))}
        {away && <li>⏳ AGOS is restarting</li>}
      </ol>
    </div>
  );
}

/** "An update is ready": what happens next, Not now / Update now. */
function ReadyCard({
  onRun,
  onDismiss,
}: {
  onRun: () => void;
  onDismiss: () => void;
}) {
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-line p-4">
      <p className="text-sm font-medium">An update is ready.</p>
      <p className="text-sm text-ink-2">
        It backs everything up first, then AGOS stops for a few minutes and
        comes back by itself. If anything fails, the old release comes back on
        its own.
      </p>
      <div className="flex justify-end gap-2">
        <Button onClick={onDismiss}>Not now</Button>
        <Button variant="primary" onClick={onRun}>
          Update now
        </Button>
      </div>
    </div>
  );
}

/** The idle row: Check update, and "up to date" when the check found nothing. */
function CheckRow({
  busy,
  check,
  onCheck,
}: {
  busy: boolean;
  check: UpdatesCheck | null;
  onCheck: () => void;
}) {
  return (
    <div className="flex items-center gap-3">
      <Button onClick={onCheck} disabled={busy}>
        {busy ? "Checking…" : "Check update"}
      </Button>
      {check && !check.ready && !busy && (
        <span className="text-sm text-ink-2">You&apos;re up to date.</span>
      )}
    </div>
  );
}

/** Everything shown while nothing runs: the note, the ready card, the result. */
function Settled({
  check,
  state,
  onRun,
  onDismiss,
}: {
  check: UpdatesCheck | null;
  state: UpdatesState | null;
  onRun: () => void;
  onDismiss: () => void;
}) {
  return (
    <>
      {check?.note ? <p className="text-sm text-ink-2">{check.note}</p> : null}
      {check?.ready && <ReadyCard onRun={onRun} onDismiss={onDismiss} />}
      {state && <Result state={state} />}
    </>
  );
}

export function UpdatesCard() {
  const [check, setCheck] = useState<UpdatesCheck | null>(null);
  const [state, setState] = useState<UpdatesState | null>(null);
  const [busy, setBusy] = useState(false);
  const [away, setAway] = useState(false);
  const [error, setError] = useState("");
  const [watching, setWatching] = useState(0);
  const running = state !== null && RUNNING.includes(state.phase);

  useUpdatesStatus(watching, setState, setAway);

  const onCheck = async () => {
    setBusy(true);
    setError("");
    const answer = await checkUpdates();
    setBusy(false);
    if (!answer.ok) setError(answer.error);
    else setCheck(answer.data);
  };

  const onRun = async () => {
    setError("");
    const answer = await runUpdates();
    if (!answer.ok) {
      setError(answer.error);
      return;
    }
    setCheck(null);
    const started = startedState(answer.data);
    if (started) setState(started);
    setWatching((n) => n + 1);
  };

  const settled = !running && !away;
  return (
    <div className="flex flex-col gap-3">
      {running || away ? (
        <Progress state={state} away={away} />
      ) : (
        <CheckRow busy={busy} check={check} onCheck={() => void onCheck()} />
      )}
      {settled && (
        <Settled
          check={check}
          state={state}
          onRun={() => void onRun()}
          onDismiss={() => setCheck(null)}
        />
      )}
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}

/** How the last update ended (nothing while none ended). */
function Result({ state }: { state: UpdatesState }) {
  if (state.phase === "done") {
    return (
      <p className="text-sm text-ink-2">
        ✓ Updated. Backups were made first; everything is back.
      </p>
    );
  }
  if (state.phase === "failed") {
    return (
      <p className="text-sm text-red-600">
        {state.half_done
          ? "AGOS itself updated, but the engine's update stopped: "
          : "The update stopped: "}
        {state.error}
        {state.rolled_back
          ? " The old release is back and everything runs on it."
          : " Tell the assistant — the backups made at the start restore everything."}
      </p>
    );
  }
  if (state.phase === "rolled-back") {
    return (
      <p className="text-sm text-ink-2">
        ↩ Rolled back. {state.steps?.at(-1)?.detail ?? ""}
      </p>
    );
  }
  return null;
}
