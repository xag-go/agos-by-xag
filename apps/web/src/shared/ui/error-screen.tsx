"use client";

import { useEffect } from "react";
import { cleanReport, rateLimit, type ErrorKind } from "@/shared/error-report";
import { Button, ButtonLink } from "@/shared/ui/button";

const allowed = rateLimit(5, 60_000);

/** Sends a broken page to Settings → Errors (best effort: never throws). */
export function reportError(
  error: unknown,
  kind: ErrorKind,
  digest?: string,
): void {
  if (!allowed()) return;
  const shown =
    error instanceof Error
      ? { name: error.name, message: error.message, stack: error.stack }
      : { message: String(error) };
  const body = cleanReport({
    ...shown,
    kind,
    digest: digest ?? "",
    url: window.location.pathname,
  });
  void fetch("/api/client-error", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    keepalive: true,
  }).catch(() => undefined);
}

/** A page that broke: what happened in plain words, Try again, and the
 * reference that matches the entry in Settings → Errors. Same look as the
 * not-found page. `whole`: the whole window (the app's own layout broke). */
export function ErrorScreen({
  error,
  reset,
  kind = "page",
  whole = false,
}: {
  error: Error & { digest?: string };
  reset: () => void;
  kind?: ErrorKind;
  whole?: boolean;
}) {
  useEffect(() => {
    reportError(error, kind, error.digest);
  }, [error, kind]);

  return (
    <main
      className={
        whole
          ? "grid min-h-dvh place-items-center p-8"
          : "grid min-h-[60dvh] place-items-center p-8"
      }
    >
      <div className="max-w-md text-center">
        <h1 className="font-display text-3xl font-semibold">
          Something went wrong
        </h1>
        <p className="mt-2 text-ink-2">
          This page hit an error and couldn&apos;t be shown. It was added to
          Settings → Errors. Try again; if it keeps happening, the error there
          says where it came from.
        </p>
        {error.digest ? (
          <p className="mt-2 text-xs text-ink-3">
            Reference: <code>{error.digest}</code>
          </p>
        ) : null}
        <div className="mt-6 flex justify-center gap-2">
          <Button variant="primary" onClick={reset}>
            Try again
          </Button>
          <ButtonLink href="/">Go home</ButtonLink>
        </div>
      </div>
    </main>
  );
}
