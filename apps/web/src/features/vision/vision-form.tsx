"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import type { PlanNode } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { Field, Input, Textarea } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { PencilIcon } from "@/shared/ui/icons";
import { saveVision } from "./actions";
import { day } from "./format";
import type { VisionPreview } from "./notes-box";
import { plural } from "@/shared/format";

/** Whole days from one ISO day to another (UTC midnights). */
function daysBetween(from: string, to: string): number | null {
  const a = Date.parse(`${from}T00:00:00Z`);
  const b = Date.parse(`${to}T00:00:00Z`);
  if (Number.isNaN(a) || Number.isNaN(b)) return null;
  return Math.round((b - a) / 86_400_000);
}

/**
 * The Vision hero at the top of the page: “Where we're going”, the Vision
 * as a serif sentence and a “Why & strategy” toggle that opens the why, the
 * strategy (the owner's own words; the Co-Founder only suggests) and the Edit
 * for all three. On the right: the days left to the latest due date of the
 * active goals, and how many goals and key results. Organize's answer from
 * the notes, or the page's “Edit vision”, opens it straight in the form
 * (saved only by Save).
 */
export function VisionHero({
  workspaceId,
  vision,
  today,
  goals,
  editing,
  onEditing,
  preview = null,
  onSaved,
}: {
  workspaceId: string;
  vision: PlanNode;
  /** Today's date (the core's, “YYYY-MM-DD”): the days left count from it. */
  today: string;
  goals: PlanNode[];
  editing: boolean;
  onEditing: (on: boolean) => void;
  preview?: VisionPreview | null;
  onSaved?: () => void;
}) {
  const [open, setOpen] = useState(preview !== null);
  const top = useRef<HTMLElement>(null);
  useEffect(() => {
    if (preview || editing)
      top.current?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [preview, editing]);
  const shownOpen = open || editing;
  const active = goals.filter((g) => g.status === "active");
  const due = active
    .map((g) => g.dueOn)
    .filter((d) => /^\d{4}-\d{2}-\d{2}$/.test(d))
    .sort()
    .at(-1);
  const left = due ? daysBetween(today, due) : null;
  const results = goals.reduce((n, g) => n + (g.results ?? []).length, 0);
  return (
    <section
      ref={top}
      id={`goal-${String(vision.id)}`}
      aria-label="Vision"
      className="vision-hero scroll-mt-6 px-5 py-5 sm:px-8 sm:py-[26px]"
    >
      <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_auto] md:items-center md:gap-10">
        <div className="min-w-0">
          <p className="text-11.5 font-bold tracking-caps text-accent uppercase">
            Where we&apos;re going
          </p>
          <p
            className={cn(
              "mt-2 mb-3 font-vision-serif text-xl leading-cozy font-medium text-balance text-hero-ink sm:text-2xl",
              !shownOpen && "line-clamp-2",
            )}
            title={shownOpen ? undefined : vision.title}
          >
            {vision.title}
          </p>
          <button
            type="button"
            className="-mx-2 inline-flex min-h-9 items-center gap-1.5 rounded-lg px-2 text-12.5 font-semibold text-accent transition-colors hover:bg-accent-soft"
            aria-expanded={shownOpen}
            aria-controls="vision-why"
            onClick={() => {
              setOpen(!shownOpen);
              if (shownOpen) onEditing(false);
            }}
          >
            Why &amp; strategy
            <svg
              aria-hidden
              viewBox="0 0 12 12"
              className={cn(
                "size-3 transition-transform duration-150",
                shownOpen && "rotate-180",
              )}
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M3 4.5 6 7.5 9 4.5" />
            </svg>
          </button>
        </div>
        <div className="text-left tabular-nums md:border-l md:border-hero-line md:pl-7 md:text-right">
          {due && left !== null && left >= 0 && (
            <>
              <p className="font-vision-serif text-30 leading-none font-semibold tracking-display text-ink">
                {left.toLocaleString("en-US")}
                <span className="ml-1 font-sans text-sm font-medium tracking-normal text-ink-3">
                  {left === 1 ? "day" : "days"}
                </span>
              </p>
              <p className="mt-1.5 text-12.5 text-ink-3">to {day(due)}</p>
            </>
          )}
          <p className="mt-0.5 text-12.5 whitespace-nowrap text-ink-3">
            {plural(goals.length, "goal")} · {plural(results, "key result")}
          </p>
        </div>
      </div>
      {shownOpen && (
        <div id="vision-why" className="mt-4 border-t border-hero-line pt-4">
          {editing ? (
            <VisionForm
              workspaceId={workspaceId}
              vision={vision}
              preview={preview}
              onSaved={() => {
                onEditing(false);
                onSaved?.();
              }}
              onCancel={() => {
                onEditing(false);
              }}
            />
          ) : (
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:gap-8">
              <dl className="grid min-w-0 flex-1 gap-4 md:grid-cols-2 md:gap-8">
                <div className="min-w-0">
                  <dt className="text-xs font-semibold tracking-wide text-ink-3 uppercase">
                    Why
                  </dt>
                  <dd className="mt-1 text-sm text-pretty whitespace-pre-wrap text-ink-2">
                    {vision.why || "Not written yet."}
                  </dd>
                </div>
                <div className="min-w-0">
                  <dt className="text-xs font-semibold tracking-wide text-ink-3 uppercase">
                    Strategy
                  </dt>
                  <dd className="mt-1 text-sm text-pretty whitespace-pre-wrap text-ink-2">
                    {vision.strategy || "Not written yet."}
                  </dd>
                </div>
              </dl>
              <Button
                variant="ghost"
                className="h-8 shrink-0 self-start px-2 text-xs"
                aria-label="Edit the Vision"
                onClick={() => {
                  onEditing(true);
                }}
              >
                <PencilIcon /> Edit
              </Button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

/** The form for the Vision, its why and the strategy: the first time on its
 * own, later inside the opened "Why & strategy". */
export function VisionForm({
  workspaceId,
  vision,
  preview = null,
  onSaved,
  onCancel,
}: {
  workspaceId: string;
  vision: PlanNode | null;
  /** Organize's answer from the notes: shown in the form, saved only by Save. */
  preview?: VisionPreview | null;
  onSaved?: () => void;
  onCancel?: () => void;
}) {
  const [title, setTitle] = useState(preview?.vision ?? vision?.title ?? "");
  const [why, setWhy] = useState(preview?.why ?? vision?.why ?? "");
  const [strategy, setStrategy] = useState(
    preview?.strategy ?? vision?.strategy ?? "",
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  return (
    <section className="vision-card flex flex-col gap-3 px-6 py-5">
      <h2 className="text-sm font-semibold">
        {vision ? "Edit the Vision" : "Write the Vision"}
      </h2>
      <p className="text-xs text-ink-3">
        One sentence for where this workspace goes, why, and how you get there.
        Every agent reads it; the Co-Founder only suggests changes.
      </p>
      {preview && (
        <p className="rounded-lg bg-accent/10 px-3 py-2 text-sm text-ink-2">
          Organized from your notes, not saved yet. Edit what you want, then
          Save.
        </p>
      )}
      <Field label="Vision">
        <Input
          value={title}
          maxLength={200}
          placeholder="The coffee brand every family in town trusts"
          onChange={(e) => {
            setTitle(e.target.value);
          }}
        />
      </Field>
      <Field label="Why">
        <Textarea
          rows={2}
          className="min-h-0"
          value={why}
          maxLength={2000}
          onChange={(e) => {
            setWhy(e.target.value);
          }}
        />
      </Field>
      <Field label="Strategy" hint="How we get there.">
        <Textarea
          rows={3}
          className="min-h-0"
          value={strategy}
          maxLength={2000}
          onChange={(e) => {
            setStrategy(e.target.value);
          }}
        />
      </Field>
      <div className="flex items-center gap-3">
        <Button
          variant="primary"
          disabled={busy || !title.trim()}
          onClick={() => {
            start(async () => {
              const r = await saveVision(workspaceId, { title, why, strategy });
              setError(r.error);
              if (!r.error) onSaved?.();
            });
          }}
        >
          {vision ? "Save" : "Set the Vision"}
        </Button>
        {vision && onCancel && (
          <Button variant="ghost" disabled={busy} onClick={onCancel}>
            Cancel
          </Button>
        )}
        <FormStatus error={error} />
      </div>
    </section>
  );
}
