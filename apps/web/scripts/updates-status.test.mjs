// The Updates card against the core's REAL contract. Core GET /updates answers
// {agos: {installed, current, check, state}, engine: {check, state}} and POST
// /updates/run answers {part, state} (services/core actions/updates.py, proved
// by its tests/test_updates.py) — never the flat {check, state} the card once
// expected, which left run progress, failure and rollback invisible. These
// tests feed the derivation the core's own payload shapes.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { withState } from "./test-stubs/react-scripted.mjs";
import {
  deriveUpdatesState,
  RUNNING,
  startedState,
} from "../src/features/settings/updates-status.ts";

const { UpdatesCard } =
  await import("../src/features/settings/updates-card.tsx");

// Updates card: useState order check, state, busy, away, error, watching.
const draw = (check, state) =>
  withState([check, state, false, false, "", 0], () =>
    renderToStaticMarkup(createElement(UpdatesCard)),
  );

const INSTALLER_NOTE =
  "This AGOS wasn't installed with the installer: update it the way you installed it.";

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

test("AGOS done while the engine part still has an update: marked, never 'everything is back'", () => {
  // The combined run starts only AGOS's part (the engine's waits for a current
  // AGOS): after the restart the engine's pending check must stay visible.
  const payload = {
    agos: {
      installed: true,
      current: { version: "0.2.0", sha: "bbbb", date: "" },
      check: { target: null },
      state: { phase: "done", started_at: "2026-11-11T10:00:00+00:00" },
    },
    engine: {
      check: { target: { version: "0.22.3", sha: "feedc0ff" } },
      state: null,
    },
  };
  const state = deriveUpdatesState(payload);
  assert.equal(state?.phase, "done");
  assert.equal(state.engine_pending, true);
  const html = draw(null, state);
  assert.match(html, /still has an update/);
  assert.doesNotMatch(html, /everything is back/);
});

test("the engine part's own done is complete: nothing pending", () => {
  const payload = {
    agos: { installed: true, check: { target: null }, state: null },
    engine: {
      check: { target: { version: "0.22.3", sha: "feedc0ff" } },
      state: { phase: "done", started_at: "2026-11-11T10:00:00+00:00" },
    },
  };
  const state = deriveUpdatesState(payload);
  assert.equal(state?.phase, "done");
  assert.ok(!state.engine_pending);
});

test("a failed check is said plainly, never 'You're up to date.'", () => {
  const html = draw(
    {
      ready: false,
      note: "The check failed.",
      agos_note: "git fetch failed: no network",
      engine_note: null,
    },
    null,
  );
  assert.match(html, /The check failed\./);
  assert.match(html, /git fetch failed: no network/);
  assert.doesNotMatch(html, /up to date/);
});

test("the installer note (agos_note) reaches the owner", () => {
  const html = draw(
    {
      ready: false,
      note: "You're up to date.",
      agos_note: INSTALLER_NOTE,
      engine_note: null,
    },
    null,
  );
  assert.match(html, /wasn&#x27;t installed with the installer/);
});

test("the engine_note reaches the owner too", () => {
  const html = draw(
    {
      ready: true,
      note: "An update is ready.",
      agos_note: null,
      engine_note: "The engine isn't set up on this machine.",
    },
    null,
  );
  assert.match(html, /isn&#x27;t set up on this machine/);
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
