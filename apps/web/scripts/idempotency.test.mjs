// The web's create / run calls carry an Idempotency-Key, and a call whose
// connection broke before any answer is sent once more with that same key
// (src/server/idempotency.ts; the core runs a keyed call at most once).
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  IDEMPOTENCY_HEADER,
  newIdempotencyKey,
  sendOnce,
} from "../src/server/idempotency.ts";

test("each owner action gets its own key", () => {
  const a = newIdempotencyKey();
  assert.match(a, /^[0-9a-f-]{36}$/);
  assert.notEqual(a, newIdempotencyKey());
  assert.equal(IDEMPOTENCY_HEADER, "Idempotency-Key");
});

test("a broken connection is sent once more, then the answer is kept", async () => {
  let tries = 0;
  const got = await sendOnce(async () => {
    tries++;
    if (tries === 1) throw new TypeError("fetch failed");
    return "made";
  });
  assert.equal(got, "made");
  assert.equal(tries, 2);
});

test("only once more: a second broken connection is the error", async () => {
  let tries = 0;
  await assert.rejects(
    sendOnce(async () => {
      tries++;
      throw new TypeError("fetch failed");
    }),
    TypeError,
  );
  assert.equal(tries, 2);
});

test("a timeout or the core's own refusal is never sent again", async () => {
  for (const error of [
    new DOMException("timed out", "TimeoutError"),
    new Error("The request was refused."),
  ]) {
    let tries = 0;
    await assert.rejects(
      sendOnce(async () => {
        tries++;
        throw error;
      }),
    );
    assert.equal(tries, 1);
  }
});
