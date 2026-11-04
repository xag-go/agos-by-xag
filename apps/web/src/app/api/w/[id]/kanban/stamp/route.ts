import type { NextRequest } from "next/server";
import { workspaceIdSchema } from "@agos/core";
import { getKanban } from "@/data/queries";
import { refuseUnlessOwner } from "@/server/access-guard";
import { stampOf } from "@/server/stamp";

/**
 * The Kanban's fingerprint, for the Kanban page's live refresh (every 3 s while
 * a card is live): a tick that finds the same fingerprint costs this one board
 * read (the core keeps it while Hermes's Kanban is unchanged) instead of a
 * re-render of the whole app with all 250 cards. Same owner check as every
 * action.
 */
export async function GET(
  _request: NextRequest,
  { params }: RouteContext<"/api/w/[id]/kanban/stamp">,
) {
  const refused = await refuseUnlessOwner();
  if (refused) return refused;
  const { id } = await params;
  if (!workspaceIdSchema.safeParse(id).success)
    return new Response("Bad request", { status: 400 });
  const board = await getKanban(id);
  return Response.json(
    { stamp: stampOf(board) },
    { headers: { "Cache-Control": "no-store" } },
  );
}

export const dynamic = "force-dynamic";
