"use client";

import { useState } from "react";
import { Button } from "@/shared/ui/button";
import {
  checkAgosUpdate,
  runAgosUpdate,
  type AgosUpdateCheck,
  type AgosUpdateState,
  type AgosUpdateStatus,
} from "./agos-update-actions";
import { short, UpdateCard, useUpdatePoll } from "./update-card";

const RUNNING = [
  "queued",
  "starting",
  "backup",
  "stopping",
  "code",
  "hermes",
  "build",
  "sandbox",
  "starting-up",
  "rollback",
];
const STEP_WORDS: Record<string, string> = {
  queued: "Starting…",
  starting: "Starting…",
  backup: "Backing everything up",
  stopping: "Pausing AGOS",
  code: "Getting the new release",
  hermes: "Updating Hermes to the release's version",
  build: "Building the new release",
  sandbox: "Rebuilding the workspace sandbox",
  "starting-up": "Starting AGOS again",
  rollback: "Something failed: putting the old release back",
};

/** Settings → General → Update AGOS: Check Update, then Update now (backups
 * first; AGOS stops for a few minutes and comes back on the new release, or on
 * the old one if anything failed). The machine's `agos update` does the work. */
export function AgosUpdateCard() {
  const [status, setStatus] = useState<AgosUpdateStatus | null>(null);
  const [check, setCheck] = useState<AgosUpdateCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const [away, setAway] = useState(false);
  const [error, setError] = useState("");
  const [watching, setWatching] = useState(0);
  const state: AgosUpdateState | null = status?.state ?? null;
  const running = state !== null && RUNNING.includes(state.phase);

  useUpdatePoll<AgosUpdateStatus>("/api/agos-update", watching, (data) => {
    if (!data) {
      // AGOS restarts during an update: keep asking until it is back.
      if (watching === 0) return null;
      setAway(true);
      return 4000;
    }
    setAway(false);
    setStatus(data);
    return data.state && RUNNING.includes(data.state.phase) ? 3000 : null;
  });

  const onCheck = async () => {
    setBusy(true);
    setError("");
    const answer = await checkAgosUpdate();
    setBusy(false);
    if (!answer.ok) setError(answer.error);
    else setCheck(answer.data);
  };

  const onRun = async () => {
    setError("");
    const answer = await runAgosUpdate();
    if (!answer.ok) {
      setError(answer.error);
      return;
    }
    setCheck(null);
    setStatus((s) => (s ? { ...s, state: answer.data } : s));
    setWatching((n) => n + 1);
  };

  if (status && !status.installed) {
    return (
      <p className="text-sm text-ink-2">
        This AGOS wasn&apos;t installed with the installer, so it is updated the
        way it was installed.
      </p>
    );
  }

  const settled = !running && !away;
  return (
    <UpdateCard
      product="AGOS"
      now={status?.current.sha ? nowLine(status.current) : null}
      progress={
        running || away
          ? {
              title: (
                <>
                  AGOS is updating{state?.to ? ` to ${short(state.to)}` : ""} —
                  it stops for a few minutes and this page comes back by itself…
                </>
              ),
              steps: state?.steps ?? [],
              current: away ? null : (state?.phase ?? null),
              words: STEP_WORDS,
              more: away && <li>⏳ AGOS is restarting</li>,
            }
          : null
      }
      busy={busy}
      upToDate={!!check && !check.target}
      onCheck={() => void onCheck()}
      error={error}
    >
      {settled && check?.target && (
        <Offer
          check={check}
          target={check.target}
          onLater={() => setCheck(null)}
          onRun={() => void onRun()}
        />
      )}
      {settled && state && <Result state={state} />}
    </UpdateCard>
  );
}

function nowLine(current: AgosUpdateStatus["current"]) {
  return {
    version: current.version ? `v${current.version}` : short(current.sha),
    detail: (
      <>
        {" "}
        ({current.version ? `${short(current.sha)}, ` : ""}
        {current.date})
      </>
    ),
  };
}

/** A new release: what it brings, what the update does, Update now / Not now. */
function Offer({
  check,
  target,
  onLater,
  onRun,
}: {
  check: AgosUpdateCheck;
  target: string;
  onLater: () => void;
  onRun: () => void;
}) {
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-line p-4">
      <p className="text-sm font-medium">
        A new AGOS release is out (
        {check.target_version
          ? `v${check.target_version}, ${short(target)}`
          : short(target)}
        ).
      </p>
      {check.news.length > 0 && (
        <ul className="max-h-48 overflow-y-auto text-sm text-ink-2">
          {check.news.map((line) => (
            <li key={line}>• {line}</li>
          ))}
        </ul>
      )}
      <p className="text-sm text-ink-2">
        The update backs everything up first
        {check.hermes_changes ? ", moves Hermes to the release's version" : ""},
        then AGOS stops for a few minutes. If anything fails, the old release
        comes back by itself.
      </p>
      <div className="flex justify-end gap-2">
        <Button onClick={onLater}>Not now</Button>
        <Button variant="primary" onClick={onRun}>
          Update now
        </Button>
      </div>
    </div>
  );
}

/** How the last update ended (nothing while none ended). */
function Result({ state }: { state: AgosUpdateState }) {
  if (state.phase === "done") {
    return (
      <p className="text-sm text-ink-2">
        ✓ Updated: {short(state.from)} → {short(state.to)}. Backups first, in
        the backups folder.
      </p>
    );
  }
  if (state.phase === "failed") {
    return (
      <p className="text-sm text-red-600">
        The update stopped: {state.error}
        {state.rolled_back ? " The old release is back." : ""}
      </p>
    );
  }
  if (state.phase === "rolled-back") {
    return (
      <p className="text-sm text-ink-2">
        ↩ Rolled back (agos rollback): {short(state.from)} → {short(state.to)}.{" "}
        {state.steps?.at(-1)?.detail ?? ""}
      </p>
    );
  }
  return null;
}
