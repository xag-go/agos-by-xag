// No engine name in the app: every owner-visible string explains what happens
// without the word "Hermes" (docs/specs/2026-11-04-no-engine-name.md). This
// scans every string literal, template part and JSX text in src/**/*.ts(x)
// (skipping *.test.*, *.d.ts and comments — comments may keep the word) and
// fails on the word outside the allowlist next to this file.
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { test } from "node:test";
import ts from "typescript";
import {
  ALLOWED_LITERALS,
  IDENTIFIER_LIKE,
  SIBLING_LANE_FILES,
} from "./no-engine-name-allowlist.mjs";

const WEB = new URL("..", import.meta.url).pathname;
const SRC = join(WEB, "src");

function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return files(path);
    if (!/\.tsx?$/.test(name)) return [];
    if (/\.test\./.test(name) || name.endsWith(".d.ts")) return [];
    return [path];
  });
}

/** Every owner-reachable text node: string literals, template parts, JSX text. */
function texts(source) {
  const found = [];
  const push = (node, text) => {
    if (text) found.push({ text, node });
  };
  const visit = (node) => {
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
      push(node, node.text);
    } else if (
      ts.isTemplateHead(node) ||
      ts.isTemplateMiddle(node) ||
      ts.isTemplateTail(node)
    ) {
      push(node, node.text);
    } else if (ts.isJsxText(node)) {
      push(node, node.text.replace(/\s+/g, " ").trim());
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return found;
}

function offenders() {
  const bad = [];
  for (const path of files(SRC)) {
    const file = relative(WEB, path);
    if (SIBLING_LANE_FILES.has(file)) continue; // owned by nhw-web lane, re-checked at integration
    const source = ts.createSourceFile(
      path,
      readFileSync(path, "utf8"),
      ts.ScriptTarget.Latest,
      false,
      path.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
    );
    for (const { text, node } of texts(source)) {
      if (!/hermes/i.test(text)) continue;
      if (IDENTIFIER_LIKE(text)) continue;
      if (ALLOWED_LITERALS.has(text)) continue;
      const { line } = source.getLineAndCharacterOfPosition(node.pos);
      bad.push(`${file}:${line + 1}: ${JSON.stringify(text)}`);
    }
  }
  return bad;
}

test("no owner-visible string says the engine's name", () => {
  const bad = offenders();
  assert.deepEqual(
    bad,
    [],
    `The engine's name leaks into owner-visible copy (reword it; identifiers/API paths are fine):\n${bad.join("\n")}`,
  );
});
