import type { NextRequest } from "next/server";
import { workspaceIdSchema } from "@agos/core";
import { getWorkspaceLog } from "@/data/queries";
import { logFilters } from "@/features/log/log-filters";
import { refuseUnlessOwner } from "@/server/access-guard";
import { stampOf } from "@/server/stamp";

/**
 * The fingerprint of the Log's first page (same filters as the page), for its
 * live refresh every 10 s: a tick with no new entry costs this one log read
 * instead of a re-render of the whole app. Same owner check as every action.
 */
export async function GET(
  request: NextRequest,
  { params }: RouteContext<"/api/w/[id]/log/stamp">,
) {
  const refused = await refuseUnlessOwner();
  if (refused) return refused;
  const { id } = await params;
  if (!workspaceIdSchema.safeParse(id).success)
    return new Response("Bad request", { status: 400 });
  const search = request.nextUrl.searchParams;
  const filters = logFilters((name) => search.get(name));
  try {
    const page = await getWorkspaceLog(id, { ...filters, before: undefined });
    return Response.json(
      { stamp: stampOf(page) },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch {
    return new Response("Unavailable", { status: 502 });
  }
}

export const dynamic = "force-dynamic";
