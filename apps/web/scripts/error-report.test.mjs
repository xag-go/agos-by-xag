// What a broken page sends to Settings → Errors: cleaned of secrets, its address
// without query or hash, one known kind, and at most N a minute.
import assert from "node:assert/strict";
import { test } from "node:test";
import { cleanReport, rateLimit } from "../src/shared/error-report.ts";

test("a report is cleaned of secrets and of the address's query", () => {
  const got = cleanReport({
    kind: "whatever",
    name: "TypeError",
    message: "failed with token=abcdef123456 and sk-abcdefghijklmnopqrstuv",
    stack: "at Page (bot1234567:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA)",
    digest: "12<script>34",
    url: "/w/acme/chats/3?key=secret#x",
  });
  assert.equal(got.kind, "page");
  assert.equal(got.message.includes("abcdef123456"), false);
  assert.equal(got.message.includes("sk-abcdefghij"), false);
  assert.match(got.message, /token=\[hidden\]/);
  assert.equal(got.stack.includes("AAAAAAAA"), false);
  assert.equal(got.digest, "12script34");
  assert.equal(got.url, "/w/acme/chats/3");
});

test("anything that isn't an object is an empty page report", () => {
  assert.deepEqual(cleanReport("boom"), {
    kind: "page",
    name: "Error",
    message: "",
    stack: "",
    digest: "",
    url: "/",
  });
  assert.equal(cleanReport({ message: "x".repeat(5000) }).message.length, 2000);
});

test("at most N reports per window", () => {
  const allowed = rateLimit(3, 60_000);
  assert.deepEqual(
    [0, 1, 2, 3].map((n) => allowed(1000 + n)),
    [true, true, true, false],
  );
  assert.equal(allowed(1000 + 60_001), true);
});
