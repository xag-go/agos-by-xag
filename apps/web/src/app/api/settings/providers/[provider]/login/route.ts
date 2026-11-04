import type { NextRequest } from "next/server";
import type { ProviderLogin } from "@/data/types";
import { bad, base, run } from "@/features/settings/provider-login-core";
import { core } from "@/server/core";
import { refuseUnlessOwner } from "@/server/access-guard";

/**
 * Where a provider login stands, for the settings page's poll (every few
 * seconds while the login waits on the provider's page). A GET route, not a
 * server action: Next runs actions one at a time, so a poll in flight made
 * every click on the page wait. Same owner check as every action.
 */
export async function GET(
  request: NextRequest,
  { params }: RouteContext<"/api/settings/providers/[provider]/login">,
) {
  const refused = await refuseUnlessOwner();
  if (refused) return refused;
  const { provider } = await params;
  const workspace = request.nextUrl.searchParams.get("workspace") ?? undefined;
  const no = bad(provider, workspace);
  const answer = no
    ? { error: no }
    : await run(() =>
        core<ProviderLogin>("GET", `${base(provider, workspace)}/login`),
      );
  return Response.json(answer, { headers: { "Cache-Control": "no-store" } });
}

export const dynamic = "force-dynamic";
