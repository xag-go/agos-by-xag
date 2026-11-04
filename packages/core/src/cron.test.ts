import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { scheduleHint } from "./cron";

describe("schedule hint (Hermes checks the schedule in core)", () => {
  it("lets through what Hermes's parser judges", () => {
    for (const ok of [
      "0 8 * * *",
      "*/15 * * * *",
      "0 9 * * 1-5",
      "0 8 * * MON",
      "every monday 9am",
      "30m",
      "60 8 * * *", // out of range: Hermes's parser says so on save
      "0 9 * * 1 30", // 6 fields: Hermes takes them (cron/jobs.py parse_schedule)
      "0 8 * *", // Hermes refuses it on save; the web never judges fields
    ]) {
      assert.equal(scheduleHint(ok), null, ok);
    }
  });

  it("hints only that there is one, and the form's length", () => {
    for (const bad of ["", "   ", "x".repeat(101)]) {
      assert.notEqual(scheduleHint(bad), null, bad);
    }
  });
});
