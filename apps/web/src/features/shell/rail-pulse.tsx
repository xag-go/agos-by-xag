"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

/** Where each workspace stands: the rail's dots and the Inbox badge. */
export type RailPulse = Record<
  string,
  { working: number; waiting: number; inbox: number }
>;

const PulseContext = createContext<RailPulse>({});

/**
 * ONE poll of /api/rail/pulse (every 5 s, 20 s when the tab is hidden) shared
 * by the rail (dots per workspace) and the sections menu (the Inbox count), so
 * a badge never costs a second request.
 */
export function RailPulseProvider({
  enabled,
  children,
}: {
  enabled: boolean;
  children: ReactNode;
}) {
  const [pulse, setPulse] = useState<RailPulse>({});
  useEffect(() => {
    if (!enabled) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        const res = await fetch("/api/rail/pulse", { cache: "no-store" });
        if (res.ok) {
          const next = (await res.json()) as RailPulse;
          if (!stop) setPulse(next);
        }
      } catch {
        // Next tick tries again.
      }
      if (!stop)
        timer = setTimeout(() => void tick(), document.hidden ? 20_000 : 5_000);
    };
    void tick();
    return () => {
      stop = true;
      if (timer) clearTimeout(timer);
    };
  }, [enabled]);
  return <PulseContext value={pulse}>{children}</PulseContext>;
}

export function useRailPulse(): RailPulse {
  return useContext(PulseContext);
}
