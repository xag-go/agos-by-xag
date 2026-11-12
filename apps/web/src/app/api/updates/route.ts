import type { CoreUpdatesStatus } from "@/features/settings/updates-status";
import { core, CoreError } from "@/server/core";
import { refuseUnlessOwner } from "@/server/access-guard";

/**
 * The update's state, for the Updates card's poll (every few seconds while an
 * update runs; AGOS itself restarts in the middle, so a failed poll just
 * waits). A GET route, not a server action: Next runs actions one at a time,
 * so a poll in flight made every click on the page wait. Same owner check as
 * every action; the core does the work.
 */
export async function GET() {
  const refused = await refuseUnlessOwner();
  if (refused) return refused;
  try {
    const data = await core<CoreUpdatesStatus>("GET", "/updates");
    return Response.json(
      { ok: true, data },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch (error) {
    if (!(error instanceof CoreError))
      return new Response("Unavailable", { status: 502 });
    return Response.json(
      { ok: false, error: error.detail },
      { headers: { "Cache-Control": "no-store" } },
    );
  }
}

export const dynamic = "force-dynamic";
