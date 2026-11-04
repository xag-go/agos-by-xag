"use client";

import { useState } from "react";
import { Button } from "@/shared/ui/button";
import { Modal } from "@/shared/ui/dialog";
import {
  checkHermesUpdate,
  runHermesUpdate,
  type HermesUpdateCheck,
  type HermesUpdateState,
  type HermesUpdateStatus,
} from "./hermes-update-actions";
import { UpdateCard, useUpdatePoll } from "./update-card";

const RUNNING = [
  "starting",
  "backups",
  "gateways-off",
  "install",
  "prepare",
  "gateways-on",
];
const STEP_WORDS: Record<string, string> = {
  starting: "Starting…",
  backups: "Backing everything up",
  "gateways-off": "Pausing the workspaces",
  install: "Installing the new Hermes",
  prepare: "Preparing every workspace on it",
  "gateways-on": "Waking the workspaces",
};

/** Settings → General → Hermes update: Check Update; a popup when one is found
 * (do it now / no); while it runs, AGOS is under maintenance and this card shows
 * each step; then the result. The core does everything (actions/hermes_update.py). */
export function HermesUpdateCard() {
  const [check, setCheck] = useState<HermesUpdateCheck | null>(null);
  const [state, setState] = useState<HermesUpdateState | null>(null);
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const running = state !== null && RUNNING.includes(state.phase);

  const [watching, setWatching] = useState(0);

  useUpdatePoll<HermesUpdateStatus>("/api/hermes-update", watching, (data) => {
    if (!data) return null;
    setState(data.state);
    return data.state && RUNNING.includes(data.state.phase) ? 2000 : null;
  });

  const onCheck = async () => {
    setBusy(true);
    setError("");
    const answer = await checkHermesUpdate();
    setBusy(false);
    if (!answer.ok) {
      setError(answer.error);
      return;
    }
    setCheck(answer.data);
    if (answer.data.target) setAsking(true);
  };

  const onRun = async () => {
    setAsking(false);
    setError("");
    const answer = await runHermesUpdate();
    if (!answer.ok) {
      setError(answer.error);
      return;
    }
    setState(answer.data);
    setWatching((n) => n + 1);
  };

  return (
    <UpdateCard
      product="Hermes"
      now={check && { version: `v${check.current.version}` }}
      progress={
        running && state
          ? {
              title: (
                <>
                  AGOS is updating Hermes
                  {state.target ? ` to v${state.target.version}` : ""} —
                  everything waits…
                </>
              ),
              steps: state.steps ?? [],
              current: state.phase,
              words: STEP_WORDS,
            }
          : null
      }
      busy={busy}
      upToDate={!!check && !check.target}
      onCheck={() => void onCheck()}
      error={error}
      popup={
        asking &&
        check?.target && (
          <Found
            check={check}
            version={check.target.version}
            onClose={() => setAsking(false)}
            onRun={() => void onRun()}
          />
        )
      }
    >
      {state && <Result state={state} />}
    </UpdateCard>
  );
}

/** How the last update ended (nothing while none ended). */
function Result({ state }: { state: HermesUpdateState }) {
  if (state.phase === "done" && state.report) {
    return (
      <p className="text-sm text-ink-2">
        ✓ Updated: v{state.report.from} → v{state.report.to}. Backups first, in{" "}
        <code className="text-xs">{state.report.backups}</code>; every workspace
        is back.
      </p>
    );
  }
  if (state.phase === "failed") {
    return (
      <p className="text-sm text-red-600">
        The update stopped: {state.error}
        {state.rolled_back
          ? " The old Hermes is back and every workspace runs on it."
          : " Tell the assistant — the backups made at the start restore everything."}
      </p>
    );
  }
  return null;
}

/** The popup when Check Update finds a release: does AGOS fit it, what's new, do it now. */
function Found({
  check,
  version,
  onClose,
  onRun,
}: {
  check: HermesUpdateCheck;
  version: string;
  onClose: () => void;
  onRun: () => void;
}) {
  return (
    <Modal label="Hermes update found" onClose={onClose}>
      <div className="flex flex-col gap-4 p-6">
        <h2 className="text-lg font-semibold">
          Hermes v{version} is out (you run v{check.current.version})
        </h2>
        {check.fits ? (
          <p className="text-sm text-ink-2">
            AGOS fits it — checked against everything AGOS uses. The update
            backs everything up first, pauses the workspaces for a few minutes,
            then brings them back on the new Hermes.
          </p>
        ) : (
          <p className="text-sm text-red-600">
            AGOS doesn&apos;t fit this release yet — it needs AGOS changes
            first. Ask the assistant; nothing can break meanwhile.
          </p>
        )}
        {check.news.length > 0 && (
          <div className="max-h-48 overflow-y-auto rounded-xl border border-line p-3">
            <p className="mb-1 text-xs font-medium uppercase text-ink-3">
              What&apos;s new ({check.news.length})
            </p>
            <ul className="flex flex-col gap-0.5 text-sm text-ink-2">
              {check.news.map((line) => (
                <li key={line}>• {line}</li>
              ))}
            </ul>
          </div>
        )}
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>No, not now</Button>
          {check.fits && (
            <Button variant="primary" onClick={onRun}>
              Do the update now
            </Button>
          )}
        </div>
      </div>
    </Modal>
  );
}
