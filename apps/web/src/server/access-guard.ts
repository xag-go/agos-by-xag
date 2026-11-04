import "server-only";
import { headers } from "next/headers";
import { notFound } from "next/navigation";
import { decideAccess } from "./access";

// AGOS has no login and no accounts: a request is let in when it comes from this
// machine or from an allowed Tailscale device (./access.ts). The proxy refuses
// every other request first; pages and server actions check again, since a
// server action can be POSTed directly.

async function allowed(): Promise<boolean> {
  const h = await headers();
  return decideAccess(h.get("host"), h.get("tailscale-user-login")) === "allow";
}

/** Every server action calls this first. */
export async function requireAccess(): Promise<void> {
  if (!(await allowed())) throw new Error("Not allowed");
}

/** For pages: a refused request sees nothing. */
export async function requireAccessPage(): Promise<void> {
  if (!(await allowed())) notFound();
}

/** For route handlers: null when the request may go on, else the 403 to send. */
export async function refuseUnlessOwner(): Promise<Response | null> {
  return (await allowed())
    ? null
    : new Response("Not allowed", { status: 403 });
}
