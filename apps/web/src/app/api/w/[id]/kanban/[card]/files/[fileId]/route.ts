import type { NextRequest } from "next/server";
import { workspaceIdSchema } from "@agos/core";
import { coreStream } from "@/server/core";
import { refuseUnlessOwner } from "@/server/access-guard";
import { copyHeaders, FILE_HEADERS } from "@/server/route-relay";

/** A file on a Kanban card (Hermes's attachment), read from the core (owner only). */
export async function GET(
  _request: NextRequest,
  { params }: RouteContext<"/api/w/[id]/kanban/[card]/files/[fileId]">,
) {
  const refused = await refuseUnlessOwner();
  if (refused) return refused;
  const { id, card, fileId } = await params;
  if (
    !workspaceIdSchema.safeParse(id).success ||
    !/^[A-Za-z0-9_-]{1,64}$/.test(card) ||
    !/^\d{1,12}$/.test(fileId)
  ) {
    return new Response("Bad request", { status: 400 });
  }
  const upstream = await coreStream(
    `/workspaces/${id}/kanban/${card}/attachments/${fileId}`,
  );
  if (!upstream.ok || !upstream.body) {
    return new Response("Not found", {
      status: upstream.status === 404 ? 404 : 502,
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
