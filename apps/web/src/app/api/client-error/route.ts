import { cleanReport, rateLimit } from "@/shared/error-report";
import { refuseUnlessOwner } from "@/server/access-guard";
import { core } from "@/server/core";

const allowed = rateLimit(10, 60_000);

/**
 * A page of the web app broke in the owner's browser (its error boundary or an
 * unhandled error): cleaned of secrets and sent to the core's Settings → Errors
 * list. Same owner check as every action; at most 10 a minute from this server
 * (the core has its own limit too). Never fails loudly: a report is best effort.
 */
export async function POST(request: Request) {
  const refused = await refuseUnlessOwner();
  if (refused) return refused;
  if (!allowed()) return new Response(null, { status: 429 });
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return new Response(null, { status: 400 });
  }
  try {
    await core("POST", "/errors/report", cleanReport(body), 10_000);
  } catch {
    return new Response(null, { status: 502 });
  }
  return new Response(null, { status: 204 });
}

export const dynamic = "force-dynamic";
