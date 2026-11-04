"use client";

import { ErrorScreen } from "@/shared/ui/error-screen";

/** A page here broke: the app's frame stays, the page says so with Try again. */
export default function PageError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <ErrorScreen error={error} reset={reset} />;
}
