import type { NextRequest } from "next/server";
import { workspaceIdSchema } from "@agos/core";
import { coreStream } from "@/server/core";
import { refuseUnlessOwner } from "@/server/access-guard";
import { copyHeaders, FILE_HEADERS } from "@/server/route-relay";

/** The workspace's export (a readable zip, no secrets), from the core (owner only). */
export async function GET(
  _request: NextRequest,
  { params }: RouteContext<"/api/w/[id]/export">,
) {
  const refused = await refuseUnlessOwner();
  if (refused) return refused;
  const { id } = await params;
  if (!workspaceIdSchema.safeParse(id).success) {
    return new Response("Bad request", { status: 400 });
  }
  const upstream = await coreStream(`/workspaces/${id}/export`);
  if (!upstream.ok || !upstream.body) {
    return new Response(await upstream.text(), {
      status: upstream.status >= 500 ? 502 : upstream.status,
    });
  }
  const headers = new Headers({
    "Cache-Control": "private, no-store",
    "X-Content-Type-Options": "nosniff",
  });
  return new Response(upstream.body, {
    headers: copyHeaders(upstream.headers, FILE_HEADERS, headers),
  });
}

export const dynamic = "force-dynamic";
