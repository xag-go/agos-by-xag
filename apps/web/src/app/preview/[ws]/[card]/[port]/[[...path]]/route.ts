import type { NextRequest } from "next/server";
import { workspaceIdSchema } from "@agos/core";
import { coreStream } from "@/server/core";
import { refuseUnlessOwner } from "@/server/access-guard";

// The preview runs the dev server's own pages and scripts. They are served under
// AGOS's address (reached only the way AGOS is, Tailscale) but in a sandbox with
// no same-origin: they can't read AGOS's cookies or call AGOS as the owner.
const SANDBOX =
  "sandbox allow-scripts allow-forms allow-popups allow-modals allow-downloads; " +
  "default-src * data: blob: 'unsafe-inline' 'unsafe-eval'; frame-ancestors 'self'";

const DROP_REQUEST = new Set([
  "cookie",
  "authorization",
  "host",
  "connection",
  "x-agos-internal",
  "content-length",
]);
const DROP_RESPONSE = new Set([
  "set-cookie",
  "content-security-policy",
  "content-encoding",
  "content-length",
  "transfer-encoding",
  "connection",
  "x-frame-options",
]);

async function relay(
  request: NextRequest,
  { params }: RouteContext<"/preview/[ws]/[card]/[port]/[[...path]]">,
) {
  const refused = await refuseUnlessOwner();
  if (refused) return refused;
  const { ws, card, port, path } = await params;
  if (
    !workspaceIdSchema.safeParse(ws).success ||
    !/^[A-Za-z0-9_-]{1,64}$/.test(card) ||
    !/^\d{4,5}$/.test(port)
  ) {
    return new Response("Bad request", { status: 400 });
  }
  const found = await coreStream(
    `/workspaces/${ws}/preview-target?card=${encodeURIComponent(card)}&port=${port}`,
  );
  if (!found.ok) {
    return new Response("This preview isn't running.", { status: 404 });
  }
  const target = (await found.json()) as { host: string; port: number };
  if (
    !/^(127\.0\.0\.1|10\.\d+\.\d+\.\d+|172\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+)$/.test(
      target.host,
    )
  ) {
    return new Response("Bad preview address", { status: 502 });
  }
  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!DROP_REQUEST.has(key.toLowerCase())) headers.set(key, value);
  });
  const rest = (path ?? []).map(encodeURIComponent).join("/");
  const url = `http://${target.host}:${String(target.port)}/${rest}${request.nextUrl.search}`;
  let upstream: Response;
  try {
    upstream = await fetch(url, {
      method: request.method,
      headers,
      body: ["GET", "HEAD"].includes(request.method)
        ? undefined
        : await request.arrayBuffer(),
      redirect: "manual",
      cache: "no-store",
    });
  } catch {
    return new Response("The preview doesn't answer (is it still starting?).", {
      status: 502,
    });
  }
  const out = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!DROP_RESPONSE.has(key.toLowerCase())) out.set(key, value);
  });
  const location = upstream.headers.get("location");
  if (location?.startsWith("/") && !location.startsWith(`/preview/${ws}/`)) {
    out.set("location", `/preview/${ws}/${card}/${port}${location}`);
  }
  out.set("Content-Security-Policy", SANDBOX);
  out.set("Cache-Control", "no-store");
  out.set("X-Content-Type-Options", "nosniff");
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export const GET = relay;
export const POST = relay;
export const PUT = relay;
export const PATCH = relay;
export const DELETE = relay;
export const HEAD = relay;

export const dynamic = "force-dynamic";
