import type { NextRequest } from "next/server";
import type { LiveView } from "@/data/types";
import { core, CoreError, seg } from "@/server/core";
import { refuseUnlessOwner } from "@/server/access-guard";

/**
 * The answer being written, for the chat page (long-poll): holds up to 20s
 * until the answer changes past `after`. Same owner check as every action.
 */
export async function GET(
  request: NextRequest,
  { params }: RouteContext<"/api/w/[id]/chats/[chatId]/live">,
) {
  const refused = await refuseUnlessOwner();
  if (refused) return refused;
  const { id, chatId } = await params;
  const after = Number(request.nextUrl.searchParams.get("after") ?? "-1");
  if (!/^\d{1,12}$/.test(chatId) || !Number.isInteger(after) || after < -1) {
    return new Response("Bad request", { status: 400 });
  }
  try {
    const view = await core<LiveView>(
      "GET",
      `/workspaces/${seg(id)}/chats/${seg(chatId)}/live?after=${String(after)}&wait=20`,
    );
    return Response.json(view, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const status = error instanceof CoreError ? error.status : 502;
    return new Response("Unavailable", { status });
  }
}

export const dynamic = "force-dynamic";
