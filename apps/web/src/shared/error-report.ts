// What the web app sends to Settings → Errors when a page breaks: the pure part
// (no secrets, short, one shape) and the per-minute limit, shared by the browser's
// reporter and the server route (app/api/client-error/route.ts).

export type ErrorKind = "page" | "app" | "server" | "unhandled";

export type ErrorReport = {
  kind: ErrorKind;
  name: string;
  message: string;
  stack: string;
  digest: string;
  url: string;
};

const KINDS: readonly ErrorKind[] = ["page", "app", "server", "unhandled"];

// Same families as the core's System Log redaction (the core wipes again).
const SECRETS: RegExp[] = [
  /bot\d{6,}:[A-Za-z0-9_-]{20,}/g,
  /\d{8,}:AA[A-Za-z0-9_-]{30,}/g,
  /whsec_[A-Za-z0-9]+/g,
  /\bsk-[A-Za-z0-9_-]{16,}/g,
  /\bgh[opsu]_[A-Za-z0-9]{20,}/g,
  /nsec1[0-9a-z]+/g,
  /(token|secret|password|authorization|api[_-]?key)(\W{1,3})[^\s,;"']{6,}/gi,
];

function scrub(text: string, max: number): string {
  let out = text;
  for (const pattern of SECRETS) {
    out = out.replace(pattern, (_match, key?: string, sep?: string) =>
      typeof key === "string" && typeof sep === "string"
        ? `${key}${sep}[hidden]`
        : "[hidden]",
    );
  }
  return out.slice(0, max);
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** The page's address without its query or hash (they can carry anything). */
function pathOf(url: string): string {
  try {
    return new URL(url, "http://agos.local").pathname.slice(0, 300);
  } catch {
    return "";
  }
}

/** One report from anything (an Error, a JSON body), cleaned. */
export function cleanReport(input: unknown): ErrorReport {
  const raw = (
    typeof input === "object" && input !== null ? input : {}
  ) as Record<string, unknown>;
  const kind = KINDS.find((k) => k === raw.kind) ?? "page";
  return {
    kind,
    name: scrub(text(raw.name) || "Error", 120),
    message: scrub(text(raw.message), 2000),
    stack: scrub(text(raw.stack), 8000),
    digest: text(raw.digest)
      .replace(/[^\w-]/g, "")
      .slice(0, 64),
    url: pathOf(text(raw.url)),
  };
}

/** At most `limit` reports per `windowMs` (an error loop sends a few, not thousands). */
export function rateLimit(limit: number, windowMs: number) {
  let times: number[] = [];
  return (now: number = Date.now()): boolean => {
    times = times.filter((t) => now - t < windowMs);
    if (times.length >= limit) return false;
    times.push(now);
    return true;
  };
}
