import type { AgosUpdateStatus } from "@/features/settings/agos-update-actions";
import { core, CoreError } from "@/server/core";
import { refuseUnlessOwner } from "@/server/access-guard";

/**
 * The AGOS update's state, for the card's poll (every few seconds while an
 * update runs; AGOS itself restarts in the middle, so a failed poll just
 * waits). Same owner check as every action; the core reads the progress file
 * `agos update` writes (actions/agos_update.py).
 */
export async function GET() {
  const refused = await refuseUnlessOwner();
  if (refused) return refused;
  try {
    const data = await core<AgosUpdateStatus>("GET", "/agos-update");
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
