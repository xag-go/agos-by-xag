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
 * Files owned by the sibling nhw-web lane (it rewrites or deletes them);
 * owned by nhw-web lane, re-checked at integration.
 */
export const SIBLING_LANE_FILES = new Set([
  "src/features/settings/sections.ts",
  "src/features/settings/lazy-sections.ts",
  "src/features/settings/settings-nav.tsx",
  "src/features/settings/update-card.tsx",
  "src/features/settings/hermes-update-card.tsx",
  "src/features/settings/agos-update-card.tsx",
  "src/features/settings/hermes-update-actions.ts",
  "src/features/settings/agos-update-actions.ts",
  "src/features/settings/hermes-settings.tsx",
  "src/features/settings/hermes-settings-actions.ts",
  "src/features/settings/hermes-settings-shared.ts",
  "src/features/settings/hermes-edit-setting.tsx",
  "src/features/settings/hermes-edit-model-pair.tsx",
  "src/features/settings/hermes-setting-row.tsx",
]);

/**
 * Identifier-like matches (no whitespace: API paths, query keys, ids,
 * CSS handles — never shown to the owner as copy) are allowed by the
 * scanner itself, except the bare word "Hermes", which IS owner copy.
 */
export const IDENTIFIER_LIKE = (text) => !/\s/.test(text) && text !== "Hermes";
