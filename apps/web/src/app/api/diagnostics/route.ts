import { core, CoreError } from "@/server/core";
import { refuseUnlessOwner } from "@/server/access-guard";

/**
 * Settings → Errors → Copy diagnostics: the core's redacted report for a GitHub
 * issue (versions, health, errors, no personal content; actions/diagnostics.py).
 * A GET route like the update polls, so it never queues behind a server action.
 */
export async function GET() {
  const refused = await refuseUnlessOwner();
  if (refused) return refused;
  try {
    const data = await core<{ madeAt: string; text: string }>(
      "GET",
      "/diagnostics",
    );
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
