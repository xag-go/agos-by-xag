"use client";

import { useEffect, useEffectEvent, useRef, type ReactNode } from "react";
import { getStatus } from "@/shared/get-status";
import { Button } from "@/shared/ui/button";

/**
 * The update card Settings → General shows twice (Update AGOS, Hermes update): what runs
 * now, Check Update, the running update's steps, then whatever the product adds (the
 * offer, the result, its popup). Owns the shared layout and the status poll; must not know
 * either product's steps, texts or actions (agos-update-card.tsx, hermes-update-card.tsx).
 */

export type UpdateStep = { name: string; at: string; detail?: string };

/** A commit's short form, as the cards show it. */
export const short = (sha?: string | null) => (sha ?? "").slice(0, 8);

/** Polls the card's GET status route while `watching` asks for it: `onAnswer` gets each
 * answer (null = no answer) and returns the wait before the next read, or null to stop. */
export function useUpdatePoll<T>(
  url: string,
  watching: number,
  onAnswer: (data: T | null) => number | null,
) {
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const answered = useEffectEvent(onAnswer);
  useEffect(() => {
    let stopped = false;
    const read = async () => {
      const answer = await getStatus<
        { ok: true; data: T } | { ok: false; error: string }
      >(url);
      if (stopped) return;
      const wait = answered(answer?.ok ? answer.data : null);
      if (wait !== null) timer.current = setTimeout(() => void read(), wait);
    };
    void read();
    return () => {
      stopped = true;
      clearTimeout(timer.current);
    };
  }, [url, watching]);
}

export function UpdateCard({
  product,
  now,
  progress,
  busy,
  upToDate,
  onCheck,
  error,
  popup,
  children,
}: {
  product: string;
  /** "<product> now: <version><detail>"; null hides the line. */
  now: { version: ReactNode; detail?: ReactNode } | null;
  /** The running update (shown instead of Check Update), null when none runs. */
  progress: {
    title: ReactNode;
    steps: UpdateStep[];
    /** The step that runs now (⏳); the others are done (✓). */
    current: string | null;
    words: Record<string, string>;
    /** One more running line after the steps (AGOS restarting). */
    more?: ReactNode;
  } | null;
  busy: boolean;
  upToDate: boolean;
  onCheck: () => void;
  error: string;
  /** Drawn last (the Hermes card's popup). */
  popup?: ReactNode;
  /** The product's own parts after Check Update: the offer, the result. */
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3">
      {now && (
        <p className="text-sm text-ink-2">
          {product} now:{" "}
          <span className="font-medium text-ink">{now.version}</span>
          {now.detail}
        </p>
      )}

      {progress ? (
        <div
          aria-live="polite"
          className="rounded-xl border border-line bg-panel-2 p-4"
        >
          <p className="text-sm font-medium">{progress.title}</p>
          <ol className="mt-2 flex flex-col gap-1 text-sm text-ink-2">
            {progress.steps.map((step) => (
              <li key={`${step.name}-${step.at}`}>
                {step.name === progress.current ? "⏳" : "✓"}{" "}
                {progress.words[step.name] ?? step.name}
              </li>
            ))}
            {progress.more}
          </ol>
        </div>
      ) : (
        <div className="flex items-center gap-3">
          <Button onClick={onCheck} disabled={busy}>
            {busy ? "Checking…" : "Check Update"}
          </Button>
          {upToDate && !busy && (
            <span className="text-sm text-ink-2">{product} is up to date.</span>
          )}
        </div>
      )}

      {children}
      {error && <p className="text-sm text-red-600">{error}</p>}
      {popup}
    </div>
  );
}
