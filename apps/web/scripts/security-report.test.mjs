// The proxy's refused requests (a Host AGOS doesn't serve, a cross-site Origin) told
// to the core: each kind has its own budget, checked BEFORE the token file is read,
// so a flood of one kind costs no file reads and never hides the other kind.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  refusedReporter,
  REFUSED_PER_MINUTE,
} from "../src/server/refused-report.ts";

function rig() {
  const sent = [];
  let reads = 0;
  let now = 1_000;
  const report = refusedReporter({
    readToken: () => {
      reads += 1;
      return "tok";
    },
    send: (body, token) => sent.push({ ...JSON.parse(body), token }),
    now: () => now,
  });
  return { report, sent, reads: () => reads, later: (ms) => (now += ms) };
}

test("a flood of one kind reads the token only within its budget", () => {
  const { report, sent, reads } = rig();
  for (let n = 0; n < REFUSED_PER_MINUTE + 50; n += 1)
    report("host", "/x?q=1", "evil.example");
  assert.equal(sent.length, REFUSED_PER_MINUTE);
  assert.equal(reads(), REFUSED_PER_MINUTE);
  assert.equal(sent[0].where, "/x");
  assert.equal(sent[0].token, "tok");
});

test("the other kind still gets through, and the window moves on", () => {
  const { report, sent, later } = rig();
  for (let n = 0; n < REFUSED_PER_MINUTE + 5; n += 1) report("host", "/", "a");
  report("origin", "/api", "https://evil.example");
  assert.equal(sent.filter((s) => s.kind === "origin").length, 1);
  later(60_001);
  report("host", "/", "a");
  assert.equal(
    sent.filter((s) => s.kind === "host").length,
    REFUSED_PER_MINUTE + 1,
  );
});

test("no token on this machine: nothing is sent", () => {
  const sent = [];
  const report = refusedReporter({
    readToken: () => null,
    send: (body) => sent.push(body),
    now: () => 0,
  });
  report("host", "/", "x");
  assert.equal(sent.length, 0);
});
