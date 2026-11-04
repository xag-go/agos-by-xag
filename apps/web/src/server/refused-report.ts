// The proxy's refused requests told to the core (System Log, source "security"):
// the pure part. Each kind has its own budget per minute, checked BEFORE the
// internal token is read, so a flood of one kind costs no file reads and never
// hides the other kind's events. Only a short safe label leaves: the path without
// its query, the Host or Origin given. ./security-report.ts wires it.

export type RefusedKind = "host" | "origin";

export const REFUSED_PER_MINUTE = 30;
const WINDOW_MS = 60_000;

export function refusedReporter(deps: {
  readToken: () => string | null;
  send: (body: string, token: string) => void;
  now: () => number;
}): (kind: RefusedKind, path: string, given: string | null) => void {
  const times: Record<RefusedKind, number[]> = { host: [], origin: [] };
  return (kind, path, given) => {
    const now = deps.now();
    const kept = times[kind].filter((t) => now - t < WINDOW_MS);
    times[kind] = kept;
    if (kept.length >= REFUSED_PER_MINUTE) return;
    kept.push(now);
    const token = deps.readToken();
    if (!token) return; // no core on this machine yet: nothing to tell
    const body = JSON.stringify({
      kind,
      where: (path.split("?", 1)[0] ?? "").slice(0, 300),
      detail: (given ?? "").slice(0, 300),
    });
    deps.send(body, token);
  };
}
