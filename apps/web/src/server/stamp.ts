import "server-only";
import { createHash } from "node:crypto";

/** A fingerprint of everything a live page shows from one core answer (the
 * whole answer, so no shown field can change without it changing). The page
 * renders with it and its live refresh asks only for it (LiveRefresh
 * `stampUrl`): the full page is re-rendered only when the answer really moved. */
export function stampOf(answer: unknown): string {
  return createHash("sha1")
    .update(JSON.stringify(answer) ?? "")
    .digest("base64url");
}
