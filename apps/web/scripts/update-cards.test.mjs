// Settings → General's Updates card drawn in each state it can be in, compared with the
// stored HTML in scripts/snapshots/update-cards.json. The stored HTML is the agreed look
// of the one-button update (docs/specs/2026-11-04-no-engine-name.md), so a refactor that
// changes one character of what the owner sees fails.
//   UPDATE_SNAPSHOTS=1 node --test --import ./scripts/tsx-loader.mjs scripts/update-cards.test.mjs
import assert from "node:assert/strict";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { withState } from "./test-stubs/react-scripted.mjs";

const { UpdatesCard } =
  await import("../src/features/settings/updates-card.tsx");

const STORED = new URL("./snapshots/update-cards.json", import.meta.url);
const updating = process.env.UPDATE_SNAPSHOTS === "1";
const stored = existsSync(STORED)
  ? JSON.parse(readFileSync(STORED, "utf8"))
  : {};
const now = {};

const steps = (...names) => names.map((name, i) => ({ name, at: String(i) }));
// Core's real installer wording, in the field core really sends (agos_note —
// the flat `note` only carries the one verdict: ready / up to date / failed).
const NOTE =
  "This AGOS wasn't installed with the installer: update it the way you installed it.";

// Updates card: useState order check, state, busy, away, error, watching.
const card = (s = {}) => [
  s.check ?? null,
  s.state ?? null,
  s.busy ?? false,
  s.away ?? false,
  s.error ?? "",
  s.watching ?? 0,
];
const STATES = {
  "first draw": card(),
  checking: card({ busy: true }),
  "up to date": card({ check: { ready: false, note: "You're up to date." } }),
  "up to date, with a note": card({
    check: { ready: false, note: "You're up to date.", agos_note: NOTE },
  }),
  "the check failed": card({
    check: {
      ready: false,
      note: "The check failed.",
      agos_note: "git fetch failed: no network",
    },
  }),
  "an update is ready": card({ check: { ready: true } }),
  "ready, with a note": card({ check: { ready: true, agos_note: NOTE } }),
  running: card({
    state: {
      phase: "build",
      steps: steps("backup", "stopping", "code", "build"),
    },
  }),
  "running, an engine step": card({
    state: {
      phase: "install",
      steps: steps("backups", "gateways-off", "install"),
    },
  }),
  "running, unknown step": card({
    state: { phase: "build", steps: steps("backup", "mystery", "build") },
  }),
  "restarting (away)": card({
    state: { phase: "starting-up", steps: steps("backup", "starting-up") },
    away: true,
    watching: 1,
  }),
  "away before any state": card({ away: true, watching: 1 }),
  done: card({ state: { phase: "done" } }),
  "done, the engine part still pending": card({
    state: { phase: "done", engine_pending: true },
  }),
  "failed, rolled back": card({
    state: { phase: "failed", error: "build broke", rolled_back: true },
  }),
  "failed, not rolled back": card({
    state: { phase: "failed", error: "disk full" },
  }),
  "failed, half done (AGOS updated, the engine part stopped)": card({
    state: {
      phase: "failed",
      error: "the fit check refused",
      rolled_back: true,
      half_done: true,
    },
  }),
  "rolled back on purpose": card({
    state: {
      phase: "rolled-back",
      steps: [{ name: "rollback", at: "1", detail: "the owner asked" }],
    },
  }),
  "an error": card({
    check: { ready: true },
    error: "Only the owner can update AGOS.",
  }),
};

for (const [name, values] of Object.entries(STATES)) {
  test(`updates card: ${name}`, () => {
    const html = withState(values, () =>
      renderToStaticMarkup(createElement(UpdatesCard)),
    );
    now[`updates: ${name}`] = html;
    if (!updating) assert.equal(html, stored[`updates: ${name}`]);
  });
}

test("every stored state is still drawn", () => {
  if (updating) {
    writeFileSync(STORED, JSON.stringify(now, null, 2) + "\n");
    return;
  }
  assert.deepEqual(Object.keys(now).sort(), Object.keys(stored).sort());
});
