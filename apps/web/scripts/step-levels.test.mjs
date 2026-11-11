// "Done by": steps as parallel levels from waits_on (display only).
import assert from "node:assert/strict";
import { test } from "node:test";
import { stepLevels } from "../src/features/setup/step-levels.ts";

const s = (key, waitsOn = []) => ({ key, waitsOn });
const keys = (levels) => levels.map((l) => l.map((x) => x.key));

test("Inspiration Watcher: intake, then two together, then Co-Founder", () => {
  const steps = [
    s("s1"),
    s("s2", ["s1"]),
    s("s4", ["s1"]),
    s("s3", ["s2", "s4"]),
  ];
  assert.deepEqual(keys(stepLevels(steps)), [["s1"], ["s2", "s4"], ["s3"]]);
});

test("a straight chain stays one step per level", () => {
  const steps = [s("a"), s("b", ["a"]), s("c", ["b"])];
  assert.deepEqual(keys(stepLevels(steps)), [["a"], ["b"], ["c"]]);
});

test("a step with no waits that is not first starts with the first level", () => {
  assert.deepEqual(keys(stepLevels([s("a"), s("b")])), [["a", "b"]]);
});

test("unknown keys are ignored", () => {
  assert.deepEqual(keys(stepLevels([s("a", ["zz"]), s("b", ["a"])])), [
    ["a"],
    ["b"],
  ]);
});

test("a cycle ends in a last level and never loops", () => {
  const out = stepLevels([s("a"), s("b", ["c"]), s("c", ["b"])]);
  assert.deepEqual(keys(out), [["a"], ["b", "c"]]);
  assert.deepEqual(stepLevels([]), []);
});

test("doneBy: parallel level groups; straight chain is as before", async () => {
  const { doneBy } = await import("../src/features/setup/step-levels.ts");
  const a = (key, agent, waitsOn = []) => ({ key, agent, waitsOn });
  const watcher = [
    a("s1", "intake"),
    a("s2", "voice", ["s1"]),
    a("s4", "video", ["s1"]),
    a("s3", null, ["s2", "s4"]),
  ];
  assert.deepEqual(doneBy(watcher), [
    [{ agent: "intake", count: 1 }],
    [
      { agent: "voice", count: 1 },
      { agent: "video", count: 1 },
    ],
    [{ agent: null, count: 1 }],
  ]);
  // the old flow(): research, ideas x3 (one per style), Co-Founder
  const chain = [
    a("1", "r"),
    a("2", "i", ["1"]),
    a("3", "i", ["2"]),
    a("4", "i", ["3"]),
    a("5", null, ["4"]),
  ];
  assert.deepEqual(doneBy(chain), [
    [{ agent: "r", count: 1 }],
    [{ agent: "i", count: 3 }],
    [{ agent: null, count: 1 }],
  ]);
});

test("a review waits on the step it reviews", () => {
  const steps = [
    s("a"),
    s("b", ["a"]),
    { key: "c", kind: "review", reviews: "b" },
  ];
  assert.deepEqual(keys(stepLevels(steps)), [["a"], ["b"], ["c"]]);
});
