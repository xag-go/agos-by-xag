// The shared card surface (src/shared/ui/panel.tsx): a screen draws a card with <Panel>, never
// by repeating its four classes, so the card looks the same everywhere and changes in one place.
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { test } from "node:test";

const WEB = new URL("..", import.meta.url).pathname;
const CARD = ["rounded-2xl", "border", "border-line", "bg-panel"];

function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return files(path);
    return name.endsWith(".tsx") ? [path] : [];
  });
}

const isCard = (classes) => {
  const list = classes.split(/\s+/);
  return CARD.every((c) => list.includes(c));
};

/** Class strings in a file that spell out the whole card surface. */
function spelledCards(text) {
  return [...text.matchAll(/(?:className=|cn\(\s*)"([^"]*)"/g)]
    .map((m) => m[1])
    .filter(isCard);
}

test("the scanner finds a spelled-out card in className and in cn()", () => {
  assert.deepEqual(
    spelledCards(
      '<section className="flex rounded-2xl border border-line bg-panel p-5">' +
        '<div className={cn("rounded-2xl border bg-panel border-line", x)}>' +
        '<div className="rounded-xl border border-line bg-panel">',
    ).length,
    2,
  );
});

test("cards use <Panel> instead of repeating its classes", () => {
  const spelled = files(join(WEB, "src"))
    .filter((p) => !p.endsWith("shared/ui/panel.tsx"))
    .flatMap((p) =>
      spelledCards(readFileSync(p, "utf8")).map(
        (c) => `${relative(WEB, p)}: ${c}`,
      ),
    );
  assert.deepEqual(spelled, []);
});
