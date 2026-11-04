import type { HermesUpdateStatus } from "@/features/settings/hermes-update-actions";
import { core, CoreError } from "@/server/core";
import { refuseUnlessOwner } from "@/server/access-guard";

/**
 * The Hermes update's state, for the card's poll (every 2 s while an update
 * runs). A GET route, not a server action: Next runs actions one at a time, so
 * a poll in flight made every click on the page wait. Same owner check as
 * every action; the core does the work (actions/hermes_update.py).
 */
export async function GET() {
  const refused = await refuseUnlessOwner();
  if (refused) return refused;
  try {
    const data = await core<HermesUpdateStatus>("GET", "/hermes-update");
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
