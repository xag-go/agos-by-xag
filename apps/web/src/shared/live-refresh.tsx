"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";
import { getStatus } from "@/shared/get-status";

/** Refreshes the page's server data while the agent is working, so the plan,
 * evidence and columns move without a reload. Stops when nothing is live.
 * With `stampUrl` (a route that answers `{ stamp }`, e.g. the board's
 * fingerprint) each tick asks only for that and re-renders the page only when
 * it differs from `stamp`, the one the page was rendered with. No answer means
 * a plain refresh, as without a stamp. */
export function LiveRefresh({
  active,
  everyMs = 3000,
  stampUrl,
  stamp,
}: {
  active: boolean;
  everyMs?: number;
  stampUrl?: string;
  stamp?: string;
}) {
  const router = useRouter();
  const seen = useRef(stamp);
  useEffect(() => {
    seen.current = stamp;
  }, [stamp]);
  useEffect(() => {
    if (!active) return;
    let asking = false;
    const timer = setInterval(() => {
      if (document.visibilityState !== "visible") return;
      if (!stampUrl) {
        router.refresh();
        return;
      }
      if (asking) return;
      asking = true;
      void getStatus<{ stamp: string }>(stampUrl).then((now) => {
        asking = false;
        if (now && now.stamp === seen.current) return;
        if (now) seen.current = now.stamp;
        router.refresh();
      });
    }, everyMs);
    return () => {
      clearInterval(timer);
    };
  }, [active, everyMs, router, stampUrl]);
  return null;
}
