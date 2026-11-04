"use client";

import { unstable_isUnrecognizedActionError } from "next/navigation";
import { useEffect } from "react";
import { reportError } from "./error-screen";

const KEY = "agos-reloaded-for-new-build";

/** After the app is rebuilt or restarted, a page that was already open still
 * calls the old build's actions ("Server Action … was not found on the
 * server"). Reloading picks up the new build; the click just needs to be
 * repeated. At most one automatic reload per 30 seconds, so it never loops.
 * Any other error nothing caught goes to Settings → Errors. */
export function ReloadOnNewBuild() {
  useEffect(() => {
    function stale(reason: unknown): boolean {
      if (!unstable_isUnrecognizedActionError(reason)) return false;
      const last = Number(sessionStorage.getItem(KEY) ?? "0");
      if (Date.now() - last < 30_000) return false;
      sessionStorage.setItem(KEY, String(Date.now()));
      window.location.reload();
      return true;
    }
    function onRejection(event: PromiseRejectionEvent) {
      if (stale(event.reason)) event.preventDefault();
      else reportError(event.reason, "unhandled");
    }
    function onError(event: ErrorEvent) {
      if (stale(event.error)) event.preventDefault();
      else reportError(event.error ?? event.message, "unhandled");
    }
    window.addEventListener("unhandledrejection", onRejection);
    window.addEventListener("error", onError);
    return () => {
      window.removeEventListener("unhandledrejection", onRejection);
      window.removeEventListener("error", onError);
    };
  }, []);
  return null;
}
