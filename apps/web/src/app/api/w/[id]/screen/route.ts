import type { NextRequest } from "next/server";
import { workspaceIdSchema } from "@agos/core";
import { coreStream } from "@/server/core";
import { refuseUnlessOwner } from "@/server/access-guard";

/** One picture of the workspace's screen (its agent's own browser / desktop,
 * inside its sandbox). Owner only; 204 when the screen is off right now. */
export async function GET(
  request: NextRequest,
  { params }: RouteContext<"/api/w/[id]/screen">,
) {
  const refused = await refuseUnlessOwner();
  if (refused) return refused;
  const { id } = await params;
  if (!workspaceIdSchema.safeParse(id).success) {
    return new Response("Bad request", { status: 400 });
  }
  const width = Number(request.nextUrl.searchParams.get("w") ?? "1440");
  const safeWidth = Number.isFinite(width)
    ? Math.max(320, Math.min(1920, Math.round(width)))
    : 1440;
  const upstream = await coreStream(
    `/workspaces/${id}/screen.jpg?width=${String(safeWidth)}`,
  );
  if (upstream.status === 204 || upstream.status === 404) {
    return new Response(null, { status: upstream.status });
  }
  if (!upstream.ok || !upstream.body) {
    return new Response("Not available", { status: 502 });
  }
  return new Response(upstream.body, {
    headers: {
      "Content-Type": "image/jpeg",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

export const dynamic = "force-dynamic";
