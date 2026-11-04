"use client";

import { useState } from "react";
import { cn } from "@/shared/ui/cn";
import { ScheduleField } from "./schedule-field";

type Start = "schedule" | "webhook" | "both";

const choices: { value: Start; label: string; hint: string }[] = [
  {
    value: "schedule",
    label: "On a schedule",
    hint: "At set times, e.g. every Monday at 9:00.",
  },
  {
    value: "webhook",
    label: "When something happens",
    hint: "The moment another app sends it (a project board, a Google Sheet, a form…).",
  },
  {
    value: "both",
    label: "Both",
    hint: "Starts at once when something happens, plus a schedule as a safety net.",
  },
];

/** When the automation starts: its schedule, a webhook, or both. */
export function StartField({
  workspaceId,
  schedule,
  scheduleDisplay,
  hook,
}: {
  workspaceId: string;
  schedule: string | undefined;
  scheduleDisplay: string | null;
  hook: boolean;
}) {
  const [start, setStart] = useState<Start>(
    hook ? (schedule ? "both" : "webhook") : "schedule",
  );
  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="mb-1.5 text-sm font-medium">When it starts</legend>
      <div role="radiogroup" className="grid gap-2 sm:grid-cols-3">
        {choices.map((c) => (
          <button
            key={c.value}
            type="button"
            role="radio"
            aria-checked={start === c.value}
            onClick={() => {
              setStart(c.value);
            }}
            className={cn(
              "rounded-xl border px-3 py-2 text-left transition-colors",
              start === c.value
                ? "border-accent bg-accent-soft"
                : "border-line hover:border-line-strong",
            )}
          >
            <span className="block text-sm font-medium">{c.label}</span>
            <span className="mt-0.5 block text-xs text-ink-2">{c.hint}</span>
          </button>
        ))}
      </div>
      <input
        type="hidden"
        name="hook"
        value={start === "schedule" ? "0" : "1"}
      />
      {start === "schedule" || start === "both" ? (
        <ScheduleField
          workspaceId={workspaceId}
          initial={schedule || (start === "both" ? "0 * * * *" : "0 8 * * *")}
          initialDisplay={schedule ? scheduleDisplay : null}
        />
      ) : (
        <>
          <input type="hidden" name="schedule" value="" />
          <p className="rounded-xl bg-sunken px-3 py-2 text-xs text-ink-2">
            After saving, open <b>Webhook</b> on the automation to copy its
            address and paste it in the other app. Each delivery starts the work
            at once; deliveries that arrive during a run are handled together in
            the next one.
          </p>
        </>
      )}
    </fieldset>
  );
}
