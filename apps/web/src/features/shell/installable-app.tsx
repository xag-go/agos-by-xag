"use client";

import { useEffect } from "react";

/**
 * Registers the service worker (public/sw.js) so the installed app works
 * like one: cached build assets, an offline page instead of a browser error,
 * and a fresh worker picked up whenever the app comes back to the foreground.
 * Renders nothing.
 */
export function InstallableApp() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    if (process.env.NODE_ENV === "development") return; // dev server: no caching
    let registration: ServiceWorkerRegistration | undefined;
    const check = () => {
      if (document.visibilityState === "visible") void registration?.update();
    };
    navigator.serviceWorker
      .register("/sw.js", { scope: "/" })
      .then((r) => {
        registration = r;
        document.addEventListener("visibilitychange", check);
      })
      .catch(() => {
        /* no service worker (private mode, old browser): the site still works */
      });
    return () => document.removeEventListener("visibilitychange", check);
  }, []);
  return null;
}
