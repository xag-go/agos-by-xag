import type { Instrumentation } from "next";

/** Every error the server hits while rendering a page or running a route or
 * action goes to Settings → Errors (with the digest the error page shows). */
export const onRequestError: Instrumentation.onRequestError = async (
  error,
  request,
) => {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;
  const { reportServerError } = await import("./server/report-error");
  await reportServerError(error, request.path);
};
