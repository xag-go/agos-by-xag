"use client";

import { ErrorScreen } from "@/shared/ui/error-screen";
import "./globals.css";

/** The app's own layout broke: the whole window, with its own html and body. */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en" className="h-full">
      <body className="min-h-full">
        <ErrorScreen error={error} reset={reset} kind="app" whole />
      </body>
    </html>
  );
}
