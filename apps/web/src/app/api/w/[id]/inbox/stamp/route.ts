import type { NextRequest } from "next/server";
import { workspaceIdSchema } from "@agos/core";
import { core, seg } from "@/server/core";
import { refuseUnlessOwner } from "@/server/access-guard";

/**
 * The Inbox's fingerprint for its live refresh: how many items wait (the core's
 * one-query count). Same owner check as every action.
 */
export async function GET(
  _request: NextRequest,
  { params }: RouteContext<"/api/w/[id]/inbox/stamp">,
) {
  const refused = await refuseUnlessOwner();
  if (refused) return refused;
  const { id } = await params;
  if (!workspaceIdSchema.safeParse(id).success)
    return new Response("Bad request", { status: 400 });
  const { count } = await core<{ count: number }>(
    "GET",
    `/workspaces/${seg(id)}/inbox/count`,
  );
  return Response.json(
    { stamp: String(count) },
    { headers: { "Cache-Control": "no-store" } },
  );
}

export const dynamic = "force-dynamic";
