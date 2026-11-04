/**
 * Who may use AGOS, decided from how the request arrived. AGOS has one user and no
 * login: the web and the core listen on 127.0.0.1 only, and a request is served
 * only when it comes
 * - from this machine (an SSH tunnel counts: it arrives on localhost), or
 * - through the owner's Tailscale (`tailscale serve`): its Host is an allowed
 *   tailnet address and Tailscale's own login header an allowed login.
 * Anything else is refused, any other Host too (DNS rebinding).
 *
 * The allowed addresses and logins are the ones Settings → Access saved (the core
 * writes them to remote-access.json beside the internal token when the owner turns
 * on "Use AGOS from other devices"), merged with AGOS_ALLOWED_HOSTS and
 * AGOS_TAILSCALE_USERS from the environment.
 */
import fs from "node:fs";
import path from "node:path";
import { internalTokenFile } from "./data-dir";

const LOCAL_HOST = /^(localhost|127\.0\.0\.1|\[::1\])(:\d{1,5})?$/;

/** How long the saved file is trusted before it is read again. */
const SAVED_FOR_MS = 3000;

export type AccessDecision = "allow" | "refuse";

type Allowed = { hosts: string[]; users: string[] };

const list = (value: string | undefined) =>
  (value ?? "")
    .split(",")
    .map((v) => v.trim().toLowerCase())
    .filter(Boolean);

const clean = (values: unknown[]) =>
  values
    .filter((v): v is string => typeof v === "string")
    .map((v) => v.trim().toLowerCase())
    .filter(Boolean);

let cache: { file: string; at: number; allowed: Allowed } | undefined;

/** What Settings → Access saved; nothing when it is off (no file). */
function saved(): Allowed {
  const file = path.join(
    path.dirname(internalTokenFile()),
    "remote-access.json",
  );
  const now = Date.now();
  if (cache?.file === file && now - cache.at < SAVED_FOR_MS)
    return cache.allowed;
  let allowed: Allowed = { hosts: [], users: [] };
  try {
    const data = JSON.parse(fs.readFileSync(file, "utf8")) as {
      host?: unknown;
      user?: unknown;
      alsoAllow?: unknown;
    };
    allowed = {
      hosts: clean([data.host]),
      users: clean([
        data.user,
        ...(Array.isArray(data.alsoAllow) ? data.alsoAllow : []),
      ]),
    };
  } catch {
    // No file (remote access off) or an unreadable one: only this machine.
  }
  cache = { file, at: now, allowed };
  return allowed;
}

function isLocalHost(host: string | null): boolean {
  return host !== null && LOCAL_HOST.test(host);
}

export function decideAccess(
  host: string | null,
  tailscaleUser: string | null,
): AccessDecision {
  if (isLocalHost(host)) return "allow";
  if (!host) return "refuse";
  const mine = saved();
  const name = host.toLowerCase().replace(/:\d{1,5}$/, "");
  const hosts = [...list(process.env.AGOS_ALLOWED_HOSTS), ...mine.hosts];
  if (!hosts.includes(name)) return "refuse";
  const user = tailscaleUser?.trim().toLowerCase();
  const users = [...list(process.env.AGOS_TAILSCALE_USERS), ...mine.users];
  return user && users.includes(user) ? "allow" : "refuse";
}
