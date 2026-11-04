import type { NextRequest } from "next/server";
import type { BotSetup } from "@/data/types";
import { core, seg } from "@/server/core";
import { refuseUnlessOwner } from "@/server/access-guard";

/**
 * The bot setup's state, polled while its QR code is on screen (the core saves
 * the bot when Telegram says it's created). A GET route, not a server action:
 * Next runs actions one at a time, so a poll in flight made every click on the
 * page wait. null = no answer. Same owner check as every action.
 */
export async function GET(
  _request: NextRequest,
  { params }: RouteContext<"/api/channels/telegram/setup/[id]">,
) {
  const refused = await refuseUnlessOwner();
  if (refused) return refused;
  const { id } = await params;
  let setup: BotSetup | null = null;
  if (/^[A-Za-z0-9_-]{8,64}$/.test(id)) {
    try {
      setup = await core<BotSetup>(
        "GET",
        `/channels/telegram/setup/${seg(id)}`,
      );
    } catch {
      setup = null;
    }
  }
  return Response.json(setup, { headers: { "Cache-Control": "no-store" } });
}

export const dynamic = "force-dynamic";
