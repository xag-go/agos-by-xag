import type { NextRequest } from "next/server";
import { workspaceIdSchema } from "@agos/core";
import { getOfficeStamp } from "@/data/queries";
import { refuseUnlessOwner } from "@/server/access-guard";

/**
 * The Office's fingerprint, for its live refresh every 2 s: one core read the
 * core answers at once while none of the stores the Office is read from moved
 * (instead of a re-render of the whole app with every card sent to the browser
 * again). Same owner check as every action.
 */
export async function GET(
  _request: NextRequest,
  { params }: RouteContext<"/api/w/[id]/office/stamp">,
) {
  const refused = await refuseUnlessOwner();
  if (refused) return refused;
  const { id } = await params;
  if (!workspaceIdSchema.safeParse(id).success)
    return new Response("Bad request", { status: 400 });
  try {
    const { stamp } = await getOfficeStamp(id);
    return Response.json(
      { stamp },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch {
    return new Response("Unavailable", { status: 502 });
  }
}

export const dynamic = "force-dynamic";
