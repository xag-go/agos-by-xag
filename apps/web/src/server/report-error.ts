import "server-only";
import { cleanReport, rateLimit } from "@/shared/error-report";
import { core } from "./core";

const allowed = rateLimit(10, 60_000);

/** A page or route the server failed to render (instrumentation.ts
 * onRequestError): into Settings → Errors, like the browser's reports. */
export async function reportServerError(
  error: unknown,
  path: string,
): Promise<void> {
  if (!allowed()) return;
  const shown =
    error instanceof Error
      ? { name: error.name, message: error.message, stack: error.stack }
      : { message: String(error) };
  const digest =
    typeof error === "object" && error !== null && "digest" in error
      ? String((error as { digest: unknown }).digest)
      : "";
  try {
    await core(
      "POST",
      "/errors/report",
      cleanReport({ ...shown, kind: "server", digest, url: path }),
      5_000,
    );
  } catch {
    // The core is down or refused it: nothing more to do from here.
  }
}
