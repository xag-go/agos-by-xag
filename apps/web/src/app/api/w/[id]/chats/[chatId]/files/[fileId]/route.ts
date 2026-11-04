import type { NextRequest } from "next/server";
import { workspaceIdSchema } from "@agos/core";
import { coreStream } from "@/server/core";
import { refuseUnlessOwner } from "@/server/access-guard";
import { copyHeaders, FILE_HEADERS } from "@/server/route-relay";

/** A screenshot, voice note or file of this chat, read from the core (owner only). */
export async function GET(
  _request: NextRequest,
  { params }: RouteContext<"/api/w/[id]/chats/[chatId]/files/[fileId]">,
) {
  const refused = await refuseUnlessOwner();
  if (refused) return refused;
  const { id, chatId, fileId } = await params;
  if (
    !workspaceIdSchema.safeParse(id).success ||
    !/^\d{1,12}$/.test(chatId) ||
    !/^\d{1,12}$/.test(fileId)
  ) {
    return new Response("Bad request", { status: 400 });
  }
  const upstream = await coreStream(
    `/workspaces/${id}/chats/${chatId}/attachments/${fileId}`,
  );
  if (!upstream.ok || !upstream.body) {
    return new Response("Not found", {
      status: upstream.status === 404 ? 404 : 502,
    });
  }
  const headers = new Headers({
    "Cache-Control": "private, max-age=3600",
    "X-Content-Type-Options": "nosniff",
  });
  return new Response(upstream.body, {
    headers: copyHeaders(upstream.headers, FILE_HEADERS, headers),
  });
}

export const dynamic = "force-dynamic";
