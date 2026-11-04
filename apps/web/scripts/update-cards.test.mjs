// Settings → General's two update cards (Update AGOS, Hermes update) drawn in each state they
// can be in, compared with the stored HTML in scripts/snapshots/update-cards.json. The cards
// share their parts (update-card-parts.tsx); the stored HTML was taken from the two cards as
// they were before, so a refactor that changes one character of what the owner sees fails.
//   UPDATE_SNAPSHOTS=1 node --test --import ./scripts/tsx-loader.mjs scripts/update-cards.test.mjs
import assert from "node:assert/strict";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { withState } from "./test-stubs/react-scripted.mjs";

const { AgosUpdateCard } =
  await import("../src/features/settings/agos-update-card.tsx");
const { HermesUpdateCard } =
  await import("../src/features/settings/hermes-update-card.tsx");

const STORED = new URL("./snapshots/update-cards.json", import.meta.url);
const updating = process.env.UPDATE_SNAPSHOTS === "1";
const stored = existsSync(STORED)
  ? JSON.parse(readFileSync(STORED, "utf8"))
  : {};
const now = {};

const SHA = "0123456789abcdef";
const TO = "fedcba9876543210";
const steps = (...names) => names.map((name, i) => ({ name, at: String(i) }));

// Update AGOS: useState order status, check, busy, away, error, watching.
const agos = (s = {}) => [
  s.status ?? null,
  s.check ?? null,
  s.busy ?? false,
  s.away ?? false,
  s.error ?? "",
  s.watching ?? 0,
];
const installed = (
  current = { version: "0.4.0", sha: SHA, date: "2026-11-01" },
  state = null,
) => ({
  installed: true,
  current,
  check: null,
  state,
});
const offer = {
  at: "t",
  ref: "main",
  current: SHA,
  target: TO,
  target_version: "0.5.0",
  news: ["Faster board", "New inbox"],
  hermes_changes: true,
};
const AGOS = {
  "first draw": agos(),
  "not installed by the installer": agos({
    status: {
      installed: false,
      current: { sha: "", date: "" },
      check: null,
      state: null,
    },
  }),
  "installed, with a version": agos({ status: installed() }),
  "installed, no version": agos({
    status: installed({ sha: SHA, date: "2026-11-01" }),
  }),
  checking: agos({ status: installed(), busy: true }),
  "up to date": agos({
    status: installed(),
    check: { ...offer, target: null, news: [] },
  }),
  "a release is out": agos({ status: installed(), check: offer }),
  "a release is out, older format": agos({
    status: installed(),
    check: { ...offer, target_version: "", news: [], hermes_changes: false },
  }),
  running: agos({
    status: installed(undefined, {
      phase: "build",
      to: TO,
      steps: steps("backup", "code", "build"),
    }),
  }),
  "running, unknown step": agos({
    status: installed(undefined, {
      phase: "build",
      steps: steps("backup", "mystery", "build"),
    }),
  }),
  "restarting (away)": agos({
    status: installed(undefined, {
      phase: "starting-up",
      to: TO,
      steps: steps("backup", "starting-up"),
    }),
    away: true,
    watching: 1,
  }),
  "away before any state": agos({
    status: installed(),
    away: true,
    watching: 1,
  }),
  done: agos({
    status: installed(undefined, { phase: "done", from: SHA, to: TO }),
  }),
  "failed, rolled back": agos({
    status: installed(undefined, {
      phase: "failed",
      error: "build broke",
      rolled_back: true,
    }),
  }),
  "failed, not rolled back": agos({
    status: installed(undefined, { phase: "failed", error: "disk full" }),
  }),
  "rolled back by agos rollback": agos({
    status: installed(undefined, {
      phase: "rolled-back",
      from: TO,
      to: SHA,
      steps: [{ name: "rollback", at: "1", detail: "the owner asked" }],
    }),
  }),
  "an error": agos({
    status: installed(),
    error: "Only the owner can update AGOS.",
  }),
};

// Hermes update: useState order check, state, asking, busy, error, watching.
const hermes = (s = {}) => [
  s.check ?? null,
  s.state ?? null,
  s.asking ?? false,
  s.busy ?? false,
  s.error ?? "",
  s.watching ?? 0,
];
const found = {
  at: "t",
  current: { version: "0.9.1", sha: SHA },
  target: { version: "0.10.0", sha: TO },
  fits: true,
  report: "",
  news: ["Better memory", "Faster tools"],
};
const HERMES = {
  "first draw": hermes(),
  "up to date": hermes({ check: { ...found, target: null, news: [] } }),
  checking: hermes({ busy: true }),
  "found, fits, popup open": hermes({ check: found, asking: true }),
  "found, does not fit, popup open": hermes({
    check: { ...found, fits: false, news: [] },
    asking: true,
  }),
  "found, popup closed": hermes({ check: found }),
  running: hermes({
    state: {
      phase: "install",
      target: found.target,
      steps: steps("backups", "gateways-off", "install"),
    },
  }),
  "running, no target, unknown step": hermes({
    state: { phase: "prepare", steps: steps("backups", "mystery", "prepare") },
  }),
  done: hermes({
    state: {
      phase: "done",
      report: {
        from: "0.9.1",
        to: "0.10.0",
        backups: "/backups/x",
        workspaces: 3,
      },
    },
  }),
  "done, no report": hermes({ state: { phase: "done" } }),
  "failed, rolled back": hermes({
    state: { phase: "failed", error: "boom", rolled_back: true },
  }),
  "failed, not rolled back": hermes({
    state: { phase: "failed", error: "boom" },
  }),
  "an error": hermes({ check: found, error: "Hermes could not be reached." }),
};

for (const [card, Component, states] of [
  ["agos", AgosUpdateCard, AGOS],
  ["hermes", HermesUpdateCard, HERMES],
]) {
  for (const [name, values] of Object.entries(states)) {
    test(`${card} update card: ${name}`, () => {
      const html = withState(values, () =>
        renderToStaticMarkup(createElement(Component)),
      );
      now[`${card}: ${name}`] = html;
      if (!updating) assert.equal(html, stored[`${card}: ${name}`]);
    });
  }
}

test("every stored state is still drawn", () => {
  if (updating) {
    writeFileSync(STORED, JSON.stringify(now, null, 2) + "\n");
    return;
  }
  assert.deepEqual(Object.keys(now).sort(), Object.keys(stored).sort());
});
