// Run history chips: a step skipped by its "Only if" reads "skipped", not "done".
import assert from "node:assert/strict";
import { test } from "node:test";
import { cardStatusText } from "../src/features/setup/run-usage.ts";

const detail = {
  steps: [
    { cardId: "t_1", key: "intake", status: "done" },
    { cardId: "t_2", key: "edit", status: "skipped", reason: "nothing new" },
  ],
};

test("a skipped step's done card reads skipped; others keep the card's status", () => {
  assert.equal(
    cardStatusText({ id: "t_2", status: "done" }, detail),
    "skipped",
  );
  assert.equal(cardStatusText({ id: "t_1", status: "done" }, detail), "done");
  assert.equal(
    cardStatusText({ id: "t_9", status: "running" }, detail),
    "running",
  );
  assert.equal(cardStatusText({ id: "t_2", status: "done" }, null), "done");
});
