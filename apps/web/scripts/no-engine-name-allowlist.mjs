// The app never shows the engine's name: owner-visible strings say what
// happens, not which program does it (docs/specs/2026-11-04-no-engine-name.md).
// This file lists the only places the word may still appear in a string
// literal or JSX text. Shrink it when you can; never grow it to silence the
// guard without the owner's spec saying so.

/**
 * Exact literals that keep the name: the spec's "Import from Hermes"
 * exception — the source/catalog entries in Connectors, Skills and
 * Capabilities (the import really reads the engine's own catalog, so the
 * name is the honest label there).
 */
export const ALLOWED_LITERALS = new Set([
  "Hermes's catalog", // Connectors: source label (connectors-catalog.tsx)
  "MCP · Hermes's catalog", // Connectors: add dialog source (connector-add.tsx)
  "From Hermes's catalog", // Skills/Capabilities: import source (library-sources.tsx)
]);

/**
 * Files owned by a sibling lane while the lanes were built in parallel.
 * Integrated now: the list stays empty — every file is scanned.
 */
export const SIBLING_LANE_FILES = new Set([]);

/**
 * Identifier-like matches (no whitespace: API paths, query keys, ids,
 * CSS handles — never shown to the owner as copy) are allowed by the
 * scanner itself — but never the WORD "Hermes" (alone or with punctuation,
 * "Hermes:", "(Hermes)"…): that IS owner copy. CamelCase identifiers
 * (saveHermesSetting) and lowercase paths (/hermes-update) have no word
 * boundary around the capitalized word and stay allowed.
 */
export const IDENTIFIER_LIKE = (text) =>
  !/\s/.test(text) && !/\bHermes\b/.test(text);
