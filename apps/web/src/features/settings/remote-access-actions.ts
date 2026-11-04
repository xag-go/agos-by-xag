"use server";

import { headers } from "next/headers";
import type { RemoteAccess } from "@/data/types";
import { type Answer as Carried, carry } from "@/server/action";
import { core } from "@/server/core";

/** Settings → Access → Use AGOS from other devices. The core does the work
 * (actions/remote_access.py: `tailscale up`, `tailscale serve`, the saved
 * address); these carry it to the owner's browser. */

type Answer = Carried<RemoteAccess>;

/** The port this web app listens on: what `tailscale serve` points at. */
async function webPort(): Promise<number> {
  const host = (await headers()).get("host") ?? "";
  const local = /^(?:localhost|127\.0\.0\.1|\[::1\]):(\d{1,5})$/.exec(host);
  const port = Number(local?.[1] ?? process.env.PORT ?? 3000);
  return Number.isInteger(port) && port > 0 && port < 65536 ? port : 3000;
}

/** The card's poll while it waits for the Tailscale login. */
export async function readRemoteAccess(): Promise<Answer> {
  return carry(() => core<RemoteAccess>("GET", "/remote-access"));
}

export async function activateRemoteAccess(): Promise<Answer> {
  const port = await webPort();
  return carry(() =>
    core<RemoteAccess>("POST", "/remote-access/activate", { port }, 60_000),
  );
}

export async function turnOffRemoteAccess(): Promise<Answer> {
  return carry(() =>
    core<RemoteAccess>("POST", "/remote-access/off", undefined, 60_000),
  );
}

export async function saveAlsoAllow(logins: string[]): Promise<Answer> {
  return carry(() =>
    core<RemoteAccess>("PUT", "/remote-access/also-allow", { logins }),
  );
}
