// Design tokens: the screens' type sizes, letter-spacing, line-heights, radii, easing, shadows
// and colors come from the theme (src/app/globals.css `@theme inline`), never from an arbitrary
// Tailwind value (`text-[11px]`, `shadow-[0_1px_2px_...]`, `bg-[#1c1d20]`). The remaining
// arbitrary values are one-off layout geometry (grid templates, calc() widths, dvh heights,
// transition property lists): their count is a ratchet that only goes down.
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { test } from "node:test";

const WEB = new URL("..", import.meta.url).pathname;
const SRC = join(WEB, "src");
// Arbitrary layout values left today; lower it when you remove some (never raise it).
const GEOMETRY_BASELINE = 167;
// `/[0.07]` stays: Tailwind writes `/7` as 7% but `/[0.07]` as 7.000000000000001%, so the
// token would not be byte-identical CSS.
const KEPT = new Set(["bg-ink/[0.07]", "border-white/[0.07]"]);

function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return files(path);
    return /\.tsx?$/.test(name) && name !== "core-api.d.ts" ? [path] : [];
  });
}

/** The utility part of a class (after its variants): `md:hover:text-[11px]` -> `text-[11px]`. */
function utility(token) {
  let depth = 0;
  let cut = -1;
  for (let i = 0; i < token.length; i++) {
    const ch = token[i];
    if (ch === "[" || ch === "(") depth++;
    else if (ch === "]" || ch === ")") depth--;
    else if (ch === ":" && depth === 0) cut = i;
  }
  return token.slice(cut + 1);
}

const TOKEN = /[^\s"'`{}]*\[[^\s"'`\]]+\][^\s"'`{}),]*/g;
// A class whose value is arbitrary: `w-[3px]`, `bg-ink/[0.045]`, `!rounded-[10px]`.
const ARBITRARY = /^!?-?[a-z][a-z0-9-]*(-\[[^\]]+\]|\/\[[0-9.]+\])[^[]*$/;

function arbitraryClasses(text) {
  return [...text.matchAll(TOKEN)]
    .map((m) => utility(m[0]))
    .filter((u) => ARBITRARY.test(u));
}

const COLOR = /^(#[0-9a-f]{3,8}|var\(--[a-z0-9-]+\)|rgba?\(.*\)|oklch\(.*\))$/i;
const LENGTH = /^[0-9.]+(px|rem|em)$/;

/** Is this arbitrary class one the theme has a token for (type, color, radius...)? */
function designValue(cls) {
  const u = cls.replace(/^!/, "");
  if (/\/\[[0-9.]+\]/.test(u)) return !KEPT.has(u); // opacity: `/4.5`, not `/[0.045]`
  const m = /^([a-z-]+?)-\[(.+)\](\/\d+)?$/.exec(u);
  if (!m) return false;
  const [, util, value] = m;
  if (
    ["tracking", "leading", "rounded", "shadow", "ease", "font"].includes(util)
  )
    return true;
  if (util === "text") return LENGTH.test(value) || COLOR.test(value);
  if (
    [
      "bg",
      "border",
      "ring",
      "ring-offset",
      "accent",
      "fill",
      "stroke",
    ].includes(util)
  )
    return COLOR.test(value);
  return false;
}

const found = files(SRC).flatMap((path) =>
  arbitraryClasses(readFileSync(path, "utf8")).map((cls) => ({
    file: relative(WEB, path),
    cls,
  })),
);

test("the scanner reads a class's utility and tells design values from geometry", () => {
  assert.deepEqual(
    arbitraryClasses(
      'className="md:hover:text-[11px] w-[calc(100%-2rem)] has-[:checked]:border-accent arm[1]"',
    ),
    ["text-[11px]", "w-[calc(100%-2rem)]"],
  );
  assert.equal(designValue("text-[11px]"), true);
  assert.equal(designValue("text-[var(--lane-ink)]"), true);
  assert.equal(designValue("shadow-[0_1px_2px_rgb(0_0_0/0.04)]"), true);
  assert.equal(designValue("bg-ink/[0.045]"), true);
  assert.equal(designValue("bg-ink/[0.07]"), false);
  assert.equal(designValue("w-[3px]"), false);
  assert.equal(designValue("grid-cols-[1fr_auto]"), false);
});

test("no screen uses an arbitrary type size, color, radius, shadow or spacing of letters", () => {
  const design = found.filter((f) => designValue(f.cls));
  assert.deepEqual(
    design,
    [],
    "use the theme token (src/app/globals.css `@theme inline`) or add one with the same value",
  );
});

test("arbitrary layout values only go down", () => {
  const geometry = found.filter((f) => !designValue(f.cls)).length;
  assert.ok(
    geometry <= GEOMETRY_BASELINE,
    `${geometry} arbitrary layout values, baseline ${GEOMETRY_BASELINE}: use the spacing scale or a token`,
  );
  assert.equal(
    geometry,
    GEOMETRY_BASELINE,
    `${geometry} arbitrary layout values: lower GEOMETRY_BASELINE to ${geometry}`,
  );
});

test("every design token in the theme is used by some screen", () => {
  const css = readFileSync(join(SRC, "app/globals.css"), "utf8");
  const block = css.slice(css.indexOf("Design tokens for the values"));
  const theme = block.slice(
    block.indexOf("@theme inline {"),
    block.indexOf("}") + 1,
  );
  const all = files(SRC)
    .map((p) => readFileSync(p, "utf8"))
    .join("\n");
  const unused = [
    ...theme.matchAll(
      /--(text|tracking|leading|radius|ease|font|color|shadow)-([^:]+):/g,
    ),
  ]
    .map(([, ns, name]) => [ns, name.split("\\.").join(".")])
    .filter(([ns, name]) => {
      const prefixes =
        ns === "color"
          ? ["text", "bg", "border", "ring", "ring-offset", "accent"]
          : [{ radius: "rounded" }[ns] ?? ns];
      return !prefixes.some((p) =>
        new RegExp(
          `[\\s"'\`:!]${p}-${name.replace(/[.]/g, "\\.")}(?![\\w.-])`,
        ).test(all),
      );
    })
    .map(([ns, name]) => `--${ns}-${name}`);
  assert.deepEqual(unused, []);
});
