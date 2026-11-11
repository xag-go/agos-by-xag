import "server-only";
import type { ProviderLogin } from "@/data/types";
import { CoreError, seg } from "@/server/core";

// Shared by the login actions and the login status route (a "use server" file
// may only export actions, so these live here).

// Hermes's provider ids (the core checks each one against Hermes's own list).
const ID = /^[a-z][a-z0-9-]{1,40}$/;
export const PROVIDERS = { has: (p: string) => ID.test(p) };

export type Result = { error: string | null; login?: ProviderLogin };

const WORKSPACE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,80}$/;

/** The login's path: General Settings' own Hermes, or one workspace's. */
export function base(provider: string, workspace?: string): string {
  const own = `/models/providers/${seg(provider)}`;
  return workspace ? `/workspaces/${seg(workspace)}${own}` : own;
}

export function bad(provider: string, workspace?: string): string | null {
  if (!PROVIDERS.has(provider)) return "Unknown provider.";
  if (workspace !== undefined && !WORKSPACE.test(workspace))
    return "Unknown workspace.";
  return null;
}

export async function run(
  fn: () => Promise<ProviderLogin | undefined>,
): Promise<Result> {
  try {
    const login = await fn();
    return login ? { error: null, login } : { error: null };
  } catch (error) {
    if (error instanceof CoreError)
      return { error: error.detail || "The engine didn't answer. Try again." };
    return { error: "AGOS didn't answer. Try again." };
  }
}
