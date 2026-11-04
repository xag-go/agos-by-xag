"use server";

import type { SecretsCheck } from "@/data/queries";
import { type Answer, carry } from "@/server/action";
import { core } from "@/server/core";

/** Settings → Health → Secrets check: keys left in every workspace's chat history
 * and logs (kind and last 4 only, never a value) and secret files with the wrong
 * permissions. Read-only; it walks every root, so it may take a minute. */
export async function runSecretsCheck(): Promise<Answer<SecretsCheck>> {
  return carry(() =>
    core<SecretsCheck>(
      "POST",
      "/preferences/secrets-check",
      undefined,
      300_000,
    ),
  );
}
