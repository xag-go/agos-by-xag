import { NextResponse, type NextRequest } from "next/server";
import { decideAccess } from "./server/access";
import { reportRefused } from "./server/security-report";

// Runs before every request (Node.js runtime): who may use AGOS (this machine or
// the owner's Tailscale, ./server/access.ts; there is no login), and a strict
// Content Security Policy with a fresh nonce.

/** A card's preview (a dev server's own pages): its route sets its own sandboxed
 * policy, so AGOS's script policy is not added there. */
const PREVIEW = /^\/preview\//;

function contentSecurityPolicy(nonce: string): string {
  const dev = process.env.NODE_ENV === "development";
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${dev ? " 'unsafe-eval'" : ""}`,
    // Dev only: Next's dev overlay injects <style> tags without a nonce.
    dev
      ? "style-src-elem 'self' 'unsafe-inline'"
      : `style-src-elem 'self' 'nonce-${nonce}'`,
    // style="…" attributes (bar widths, menu position) carry no script.
    "style-src-attr 'unsafe-inline'",
    // Composio's app logos (its app picker in a workspace's Connectors).
    "img-src 'self' blob: data: https://logos.composio.dev",
    // Voice notes: recorded in the page (blob:) and played from this site.
    "media-src 'self' blob:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
}

/** A change (not a read) a browser sent from another site: its Origin is not this
 * Host ("null" included). Next checks its server actions the same way; this
 * covers every other route too. A call with no Origin (not a browser: Hermes, an
 * MCP client) is left to the route's own check. */
function crossSite(request: NextRequest): boolean {
  if (["GET", "HEAD", "OPTIONS"].includes(request.method)) return false;
  const origin = request.headers.get("origin");
  if (origin === null) return false;
  try {
    // The Host Next's own server-action check compares with.
    const host =
      request.headers.get("x-forwarded-host") ?? request.headers.get("host");
    return new URL(origin).host !== host;
  } catch {
    return true;
  }
}

export async function proxy(request: NextRequest) {
  const access = decideAccess(
    request.headers.get("host"),
    request.headers.get("tailscale-user-login"),
  );
  if (access === "refuse") {
    reportRefused(
      "host",
      request.nextUrl.pathname,
      request.headers.get("host"),
    );
    return new NextResponse(
      "AGOS opens only on this machine or over the owner's Tailscale.",
      { status: 403 },
    );
  }

  if (PREVIEW.test(request.nextUrl.pathname)) return NextResponse.next();

  if (crossSite(request)) {
    reportRefused(
      "origin",
      request.nextUrl.pathname,
      request.headers.get("origin"),
    );
    return new NextResponse(
      "AGOS doesn't take changes sent from another site.",
      {
        status: 403,
      },
    );
  }

  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const csp = contentSecurityPolicy(nonce);
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  // Static build assets don't need the checks; everything else does, the image
  // optimizer (/_next/image) included: a request that skips this proxy skips the
  // Host/Tailscale check too.
  matcher: ["/((?!_next/static|favicon.ico).*)"],
};
