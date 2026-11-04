import { core } from "@/server/core";

/** Container health check: the app answers and reaches the core. */
export async function GET() {
  await core("GET", "/health");
  return Response.json({ ok: true });
}

export const dynamic = "force-dynamic";
