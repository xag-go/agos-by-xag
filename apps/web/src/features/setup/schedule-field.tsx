"use client";

import { scheduleHint } from "@agos/core/cron";
import { useEffect, useState } from "react";
import { scheduleText } from "./actions";
import { Field, Input, Select } from "@/shared/ui/field";
import {
  describeCron,
  fromCron,
  hourIntervals,
  toCron,
  weekdays,
  type Schedule,
} from "./schedule";

const kinds: { value: Schedule["kind"]; label: string }[] = [
  { value: "daily", label: "Every day" },
  { value: "weekdays", label: "Weekdays (Mon–Fri)" },
  { value: "weekly", label: "Once a week" },
  { value: "monthly", label: "Once a month" },
  { value: "hours", label: "Every few hours" },
  { value: "custom", label: "Custom (cron or plain words)" },
];

function switchKind(kind: Schedule["kind"], current: Schedule): Schedule {
  const time = "time" in current ? current.time : "08:00";
  switch (kind) {
    case "daily":
    case "weekdays":
      return { kind, time };
    case "weekly":
      return { kind, time, day: 1 };
    case "monthly":
      return { kind, time, date: 1 };
    case "hours":
      return { kind, every: 4, minute: 0 };
    case "custom":
      return { kind, cron: toCron(current) };
  }
}

/**
 * Pick a common schedule from menus, or write any cron expression. Either way
 * the form submits one schedule string. Hermes's own parser checks it when it
 * is saved (core); the form gives only a light hint while typing.
 */
export function ScheduleField({
  workspaceId,
  initial,
  initialDisplay = null,
  name = "schedule",
}: {
  workspaceId: string;
  initial: string;
  /** Hermes's own words for the saved schedule (its job's schedule_display). */
  initialDisplay?: string | null;
  name?: string;
}) {
  const [schedule, setSchedule] = useState<Schedule>(() => fromCron(initial));
  const cron = toCron(schedule);
  const error = scheduleHint(cron);
  // A custom schedule: Hermes's own reading of it (its parser), asked as he types.
  const [hermes, setHermes] = useState<{
    text: string;
    display: string | null;
    problem: string | null;
  }>({ text: initial, display: initialDisplay, problem: null });
  const custom = schedule.kind === "custom";
  useEffect(() => {
    if (!custom || error || cron === hermes.text) return;
    const timer = setTimeout(() => {
      void scheduleText(workspaceId, cron).then((r) => {
        setHermes({ text: cron, ...r });
      });
    }, 400);
    return () => {
      clearTimeout(timer);
    };
  }, [custom, cron, error, hermes.text, workspaceId]);
  const fromHermes = hermes.text === cron ? hermes : null;

  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="mb-1.5 text-sm font-medium">When</legend>
      <div className="grid gap-3 sm:grid-cols-2">
        <Select
          aria-label="Repeat"
          value={schedule.kind}
          onChange={(e) => {
            setSchedule(
              switchKind(e.target.value as Schedule["kind"], schedule),
            );
          }}
        >
          {kinds.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </Select>

        {"time" in schedule && (
          <Input
            type="time"
            aria-label="Time"
            value={schedule.time}
            required
            onChange={(e) => {
              setSchedule({ ...schedule, time: e.target.value });
            }}
          />
        )}

        {schedule.kind === "weekly" && (
          <Select
            aria-label="Day of the week"
            value={schedule.day}
            onChange={(e) => {
              setSchedule({ ...schedule, day: Number(e.target.value) });
            }}
          >
            {weekdays.map((d, i) => (
              <option key={d} value={i}>
                {d}
              </option>
            ))}
          </Select>
        )}

        {schedule.kind === "monthly" && (
          <Select
            aria-label="Day of the month"
            value={schedule.date}
            onChange={(e) => {
              setSchedule({ ...schedule, date: Number(e.target.value) });
            }}
          >
            {Array.from({ length: 28 }, (_, i) => i + 1).map((d) => (
              <option key={d} value={d}>
                Day {d}
              </option>
            ))}
          </Select>
        )}

        {schedule.kind === "hours" && (
          <Select
            aria-label="Interval"
            value={schedule.every}
            onChange={(e) => {
              setSchedule({ ...schedule, every: Number(e.target.value) });
            }}
          >
            {hourIntervals.map((h) => (
              <option key={h} value={h}>
                Every {h === 1 ? "hour" : `${h} hours`}
              </option>
            ))}
          </Select>
        )}

        {schedule.kind === "custom" && (
          <Field
            label="Schedule"
            hint="A cron expression (minute · hour · day of month · month · day of week), or plain forms: “every 30m”, “every monday 9am”."
          >
            <Input
              value={schedule.cron}
              spellCheck={false}
              aria-invalid={error !== null}
              className="font-mono"
              onChange={(e) => {
                setSchedule({ kind: "custom", cron: e.target.value });
              }}
            />
          </Field>
        )}
      </div>

      <p className="text-sm" aria-live="polite">
        {error || fromHermes?.problem ? (
          <span className="text-danger">
            Can&apos;t use this schedule: {error ?? fromHermes?.problem}.
          </span>
        ) : (
          <>
            <span className="text-ink">
              {describeCron(cron, fromHermes?.display)}
            </span>{" "}
            <code className="rounded bg-sunken px-1.5 py-0.5 text-xs text-ink-2">
              {cron}
            </code>
          </>
        )}
      </p>
      <input type="hidden" name={name} value={cron} />
    </fieldset>
  );
}
