import type { NextRequest } from "next/server";
import { workspaceIdSchema } from "@agos/core";
import { coreStream } from "@/server/core";

/** An outside assistant's MCP call (Streamable HTTP, JSON answers) into one
 * workspace: its Bearer token goes to the core, which lets it into that
 * workspace only (Settings → Connections). */
export async function POST(
  request: NextRequest,
  { params }: RouteContext<"/api/mcp/[ws]">,
) {
  const { ws } = await params;
  if (!workspaceIdSchema.safeParse(ws).success) {
    return new Response("Bad request", { status: 400 });
  }
  const given = request.headers.get("authorization") ?? "";
  const bearer = /^Bearer\s+(\S{10,200})$/i.exec(given)?.[1];
  if (!bearer) {
    return Response.json(
      { error: "Send the workspace's token: Authorization: Bearer <token>." },
      { status: 401, headers: { "WWW-Authenticate": "Bearer" } },
    );
  }
  const body = await request.text();
  if (body.length > 1_000_000) {
    return new Response("Too large", { status: 413 });
  }
  const upstream = await coreStream(`/workspaces/${ws}/mcp-serve`, {
    method: "POST",
    headers: {
      "x-agos-mcp-token": bearer,
      "content-type": "application/json",
    },
    body,
  });
  if (upstream.status === 401) {
    return Response.json(
      { error: "This token doesn't open this workspace." },
      { status: 401, headers: { "WWW-Authenticate": "Bearer" } },
    );
  }
  if (upstream.status === 202) return new Response(null, { status: 202 });
  return new Response(await upstream.text(), {
    status: upstream.status,
    headers: {
      "content-type": "application/json",
      "cache-control": "no-store",
    },
  });
}

/** No server-sent stream: answers come back on the POST (the spec allows 405). */
export function GET() {
  return new Response("Method not allowed", {
    status: 405,
    headers: { Allow: "POST" },
  });
}

export const dynamic = "force-dynamic";
