// Guard: every export of the web app and of @agos/core is used: imported by another
// file, or at least used in its own. A leftover (an old page's helper, a component
// nobody renders) fails this test instead of waiting for the next audit. Tests
// don't count as users.
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const web = join(dirname(fileURLToPath(import.meta.url)), "..");
const roots = [
  join(web, "src"),
  join(web, "..", "..", "packages", "core", "src"),
];

// Names Next.js itself reads from a page, layout or route file.
const NEXT = new Set([
  "default",
  "metadata",
  "generateMetadata",
  "generateStaticParams",
  "generateViewport",
  "viewport",
  "dynamic",
  "dynamicParams",
  "revalidate",
  "runtime",
  "fetchCache",
  "preferredRegion",
  "maxDuration",
  "config",
  "proxy",
  "GET",
  "POST",
  "PUT",
  "PATCH",
  "DELETE",
  "HEAD",
  "OPTIONS",
]);

function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return files(path);
    return /\.(ts|tsx|mjs)$/.test(name) && !name.endsWith(".d.ts")
      ? [path]
      : [];
  });
}

const all = roots.flatMap(files);
const isTest = (path) => /\.test\.(ts|tsx|mjs)$/.test(path);
const text = new Map(all.map((path) => [path, readFileSync(path, "utf8")]));
const EXPORT =
  /^export\s+(?:declare\s+)?(?:async\s+)?(?:function\*?|const|let|class|type|interface|enum)\s+([A-Za-z_$][\w$]*)/gm;

test("every export is used", () => {
  const unused = [];
  for (const [path, source] of text) {
    if (isTest(path)) continue;
    for (const [, name] of source.matchAll(EXPORT)) {
      if (NEXT.has(name)) continue;
      const pattern = `\\b${name.replace(/\$/g, "\\$")}\\b`;
      const word = new RegExp(pattern);
      const here = source.match(new RegExp(pattern, "g"))?.length ?? 0;
      const used =
        here > 1 ||
        [...text].some(
          ([other, body]) =>
            other !== path && !isTest(other) && word.test(body),
        );
      if (!used) unused.push(`${relative(web, path)}: ${name}`);
    }
  }
  assert.deepEqual(unused, []);
});
