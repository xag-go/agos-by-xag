// Module hooks for scripts/tsx-loader.mjs: resolve `@/` and extensionless .ts/.tsx imports,
// transpile .ts/.tsx with TypeScript (types dropped, JSX -> react/jsx-runtime). Modules that
// only run on the server or inside Next (`server-only`, `next/navigation`...) get the small
// stand-ins in scripts/test-stubs/, so a component renders in a plain node process.
import { existsSync, readFileSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const SRC = join(WEB, "src");
const STUBS = join(WEB, "scripts", "test-stubs");
const ts = createRequire(join(WEB, "../../package.json"))("typescript");
const STUBBED = {
  "server-only": "server-only.mjs",
  "next/navigation": "next-navigation.mjs",
  "next/link": "next-link.mjs",
};

function file(base) {
  for (const candidate of [
    base,
    `${base}.ts`,
    `${base}.tsx`,
    join(base, "index.ts"),
    join(base, "index.tsx"),
  ]) {
    if (existsSync(candidate) && statSync(candidate).isFile()) return candidate;
  }
  return null;
}

export async function resolve(specifier, context, next) {
  if (specifier in STUBBED) {
    return {
      url: pathToFileURL(join(STUBS, STUBBED[specifier])).href,
      shortCircuit: true,
    };
  }
  if (
    specifier === "react" &&
    context.parentURL?.startsWith(pathToFileURL(SRC).href)
  ) {
    return {
      url: pathToFileURL(join(STUBS, "react-scripted.mjs")).href,
      shortCircuit: true,
    };
  }
  let base = null;
  if (specifier.startsWith("@/")) base = join(SRC, specifier.slice(2));
  else if (
    specifier.startsWith(".") &&
    context.parentURL?.startsWith("file:") &&
    /\.(ts|tsx)$/.test(context.parentURL)
  ) {
    base = join(dirname(fileURLToPath(context.parentURL)), specifier);
  }
  const found = base && file(base);
  if (found) return { url: pathToFileURL(found).href, shortCircuit: true };
  return next(specifier, context);
}

export async function load(url, context, next) {
  if (!/\.(ts|tsx)$/.test(url) || !url.startsWith("file:"))
    return next(url, context);
  const path = fileURLToPath(url);
  const text = readFileSync(path, "utf8");
  if (/^\s*["']use server["']/.test(text)) {
    // A server action module: each action becomes a stub a test can replace through
    // globalThis.__serverActions[name] (no server code runs in a unit test).
    const names = [
      ...text.matchAll(/^export\s+async\s+function\s+(\w+)/gm),
    ].map((m) => m[1]);
    const source = names
      .map(
        (n) =>
          `export async function ${n}(...args) { const f = globalThis.__serverActions?.[${JSON.stringify(n)}]; if (!f) throw new Error("server action ${n} called in a test"); return f(...args); }`,
      )
      .join("\n");
    return { format: "module", source, shortCircuit: true };
  }
  const out = ts.transpileModule(text, {
    fileName: path,
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
      verbatimModuleSyntax: false,
      inlineSourceMap: true,
      inlineSources: true,
    },
  });
  return { format: "module", source: out.outputText, shortCircuit: true };
}
