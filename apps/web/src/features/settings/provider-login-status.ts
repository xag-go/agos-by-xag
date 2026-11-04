import type { ProviderLogin } from "@/data/types";
import { getStatus } from "@/shared/get-status";

/** Where a login stands, polled while it waits on the provider's page (GET
 * /api/settings/providers/[provider]/login, not a server action, so a click
 * on the page never waits behind a poll). When it says "done", the caller
 * refreshes the page so the new sign-in shows. */
export async function providerLoginStatus(
  provider: string,
  workspace?: string,
): Promise<{ error: string | null; login?: ProviderLogin }> {
  const query = workspace ? `?workspace=${encodeURIComponent(workspace)}` : "";
  return (
    (await getStatus<{ error: string | null; login?: ProviderLogin }>(
      `/api/settings/providers/${encodeURIComponent(provider)}/login${query}`,
    )) ?? { error: "AGOS didn't answer. Try again." }
  );
}
