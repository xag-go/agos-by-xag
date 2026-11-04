// No zod here: the browser imports this file (the new-workspace form), and zod
// with its locales is ~88 KB gz of JavaScript for one regex. The server's
// workspaceIdSchema (./workspace.ts) is built from this same pattern.

/**
 * A workspace id is fixed at creation and becomes its folder name on disk, so
 * it is restricted to a safe alphabet: no dots, slashes or leading dashes means
 * no path traversal. The display name is separate and can change freely.
 */
export const WORKSPACE_ID_PATTERN = /^[a-z0-9][a-z0-9-]{0,62}$/;

/** "Argan Store 2" → "argan-store-2": the id a new workspace gets. */
export function workspaceIdFromName(name: string): string {
  return name
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 63)
    .replace(/-+$/, "");
}
