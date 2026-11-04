"use client";

import { createContext, useContext, type ReactNode } from "react";
import type { components } from "@/data/core-api";

/** Limits the core keeps (GET /app/facts), read once per page by the layout so
 * the web never repeats them. */
export type AppFacts = components["schemas"]["AppFacts"];

const Facts = createContext<AppFacts | null>(null);

export function AppFactsProvider({
  facts,
  children,
}: {
  facts: AppFacts | null;
  children: ReactNode;
}) {
  return <Facts.Provider value={facts}>{children}</Facts.Provider>;
}

/** The core's limits; null when they couldn't be read (the core still checks). */
export function useAppFacts(): AppFacts | null {
  return useContext(Facts);
}
