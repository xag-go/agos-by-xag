/**
 * A request the proxy refused (a Host AGOS doesn't serve, a cross-site Origin),
 * told to the core for the System Log (source "security"). Never waits, never
 * fails the answer, at most REFUSED_PER_MINUTE per kind a minute (checked before
 * the token file is read), and only a short safe label: the path without its
 * query, the Host or Origin given. No cookie, header value or token is sent.
 *
 * Not "server-only": the proxy runs it (src/proxy.ts), like ./access.ts.
 */
import fs from "node:fs";
import { internalTokenFile } from "./data-dir";
import { refusedReporter } from "./refused-report";

export type { RefusedKind } from "./refused-report";

export const reportRefused = refusedReporter({
  readToken: () => {
    try {
      return fs.readFileSync(internalTokenFile(), "utf8").trim() || null;
    } catch {
      return null;
    }
  },
  send: (body, token) => {
    const core = process.env.AGOS_CORE_URL?.trim() || "http://127.0.0.1:8766";
    void fetch(`${core.replace(/\/$/, "")}/security/events`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-agos-internal": token },
      body,
      signal: AbortSignal.timeout(2_000),
    }).catch(() => undefined);
  },
  now: () => Date.now(),
});
