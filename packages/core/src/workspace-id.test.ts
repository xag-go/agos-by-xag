import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { workspaceIdSchema } from "./workspace";
import { WORKSPACE_ID_PATTERN, workspaceIdFromName } from "./workspace-id";

describe("workspace id rule (browser regex = server schema)", () => {
  it("agrees with the server's schema on every id", () => {
    for (const id of [
      "argan-store-2",
      "a",
      "0",
      "x".repeat(63),
      "x".repeat(64),
      "",
      "-lead",
      "Upper",
      "dots.no",
      "../up",
      "a/b",
      "trailing-",
      "sp ace",
    ]) {
      assert.equal(
        WORKSPACE_ID_PATTERN.test(id),
        workspaceIdSchema.safeParse(id).success,
        id,
      );
    }
  });

  it("turns a name into a valid id", () => {
    assert.equal(workspaceIdFromName("Argan Store 2"), "argan-store-2");
    assert.equal(
      workspaceIdFromName("Crème Brûlée — Rabat"),
      "creme-brulee-rabat",
    );
    assert.ok(WORKSPACE_ID_PATTERN.test(workspaceIdFromName("-- Café 9 --")));
  });
});
