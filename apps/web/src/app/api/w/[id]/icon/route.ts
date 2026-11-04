import type { NextRequest } from "next/server";
import { workspaceIdSchema } from "@agos/core";
import { coreStream } from "@/server/core";
import { refuseUnlessOwner } from "@/server/access-guard";
import { copyHeaders } from "@/server/route-relay";

/** The workspace's icon, read from the core (owner only). The address carries
 * the record's `icon` stamp (`?v=`), so the core's long cache is safe: a new
 * picture has a new address. */
export async function GET(
  _request: NextRequest,
  { params }: RouteContext<"/api/w/[id]/icon">,
) {
  const refused = await refuseUnlessOwner();
  if (refused) return refused;
  const { id } = await params;
  if (!workspaceIdSchema.safeParse(id).success) {
    return new Response("Bad request", { status: 400 });
  }
  const upstream = await coreStream(`/workspaces/${id}/icon`);
  if (!upstream.ok || !upstream.body) {
    return new Response("Not found", {
      status: upstream.status === 404 ? 404 : 502,
    });
  }
  const headers = copyHeaders(
    upstream.headers,
    [
      "content-type",
      "content-length",
      "cache-control",
      "content-security-policy",
    ],
    new Headers({ "X-Content-Type-Options": "nosniff" }),
  );
  return new Response(upstream.body, { headers });
}

export const dynamic = "force-dynamic";
