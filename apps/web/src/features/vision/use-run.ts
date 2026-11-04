"use client";

import { useState, useTransition } from "react";

export type Run = (job: () => Promise<{ error: string | null }>) => void;

/** One server action at a time: busy while it runs, its error after. */
export function useRun(): [boolean, string | null, Run] {
  const [busy, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const run: Run = (job) => {
    start(async () => {
      const r = await job();
      setError(r.error);
    });
  };
  return [busy, error, run];
}
