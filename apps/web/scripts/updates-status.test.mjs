// The Updates card against the core's REAL contract. Core GET /updates answers
// {agos: {installed, current, check, state}, engine: {check, state}} and POST
// /updates/run answers {part, state} (services/core actions/updates.py, proved
// by its tests/test_updates.py) — never the flat {check, state} the card once
// expected, which left run progress, failure and rollback invisible. These
// tests feed the derivation the core's own payload shapes.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import {
  deriveUpdatesState,
  RUNNING,
  startedState,
} from "../src/features/settings/updates-status.ts";

const core = (agosState, engineState) => ({
  agos: {
    installed: true,
    current: { version: "0.2.0", sha: "aaaa", date: "" },
    check: null,
    state: agosState,
  },
  engine: { check: null, state: engineState },
});
const steps = (...names) => names.map((name, i) => ({ name, at: String(i) }));

test("an AGOS update in flight is shown as the running state", () => {
  const state = deriveUpdatesState(
    core(
      {
        phase: "build",
        started_at: "2026-11-11T10:00:00+00:00",
        steps: steps("backup", "stopping", "code", "build"),
        error: null,
      },
      null,
    ),
  );
  assert.equal(state?.phase, "build");
  assert.ok(RUNNING.includes(state.phase));
});

test("an engine update in flight is shown as the running state", () => {
  const state = deriveUpdatesState(
    core(null, {
      phase: "install",
      started_at: "2026-11-11T10:00:00+00:00",
      steps: steps("backups", "gateways-off", "install"),
      error: null,
    }),
  );
  assert.equal(state?.phase, "install");
});

test("no update ever ran: nothing to show", () => {
  assert.equal(deriveUpdatesState(core(null, null)), null);
  assert.equal(deriveUpdatesState({}), null);
});

test("a failure is shown with its error and rollback word", () => {
  const state = deriveUpdatesState(
    core(
      {
        phase: "failed",
        started_at: "2026-11-11T10:00:00+00:00",
        error: "build broke",
        rolled_back: true,
      },
      null,
    ),
  );
  assert.equal(state?.phase, "failed");
  assert.equal(state.error, "build broke");
  assert.equal(state.rolled_back, true);
});

test("half done is a failure the owner sees: AGOS updated, the engine part stopped", () => {
  const state = deriveUpdatesState(
    core(
      {
        phase: "done",
        started_at: "2026-11-11T10:00:00+00:00",
        finished_at: "2026-11-11T10:10:00+00:00",
      },
      {
        phase: "failed",
        started_at: "2026-11-11T10:20:00+00:00",
        error: "the fit check refused",
        rolled_back: true,
      },
    ),
  );
  assert.equal(state?.phase, "failed");
  assert.equal(state.half_done, true);
  assert.equal(state.error, "the fit check refused");
});

test("while nothing runs, the latest word wins", () => {
  const state = deriveUpdatesState(
    core(
      { phase: "done", started_at: "2026-11-11T10:00:00+00:00" },
      { phase: "done", started_at: "2026-11-01T10:00:00+00:00" },
    ),
  );
  assert.equal(state?.started_at, "2026-11-11T10:00:00+00:00");
});

test("Update now answers {part, state}: the card keeps the state, not the envelope", () => {
  const state = startedState({
    part: "agos",
    state: { phase: "queued", started_at: "2026-11-11T10:00:00+00:00" },
  });
  assert.equal(state?.phase, "queued");
});

test("the card and its poll route read the core's real payload", () => {
  const card = readFileSync(
    new URL("../src/features/settings/updates-card.tsx", import.meta.url),
    "utf8",
  );
  assert.match(card, /deriveUpdatesState\(/);
  assert.match(card, /startedState\(/);
  const route = readFileSync(
    new URL("../src/app/api/updates/route.ts", import.meta.url),
    "utf8",
  );
  assert.match(route, /CoreUpdatesStatus/);
});
