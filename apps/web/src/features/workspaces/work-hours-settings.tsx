"use client";

import { useState, useTransition } from "react";
import type { DaySpan, WorkHours } from "@/data/types";
import { ShiftChip } from "@/features/workers/shift-chip";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { Switch } from "@/shared/ui/switch";
import { saveWorkHours, setStayOnToday } from "./work-hours-actions";
import { PanelSection } from "@/shared/ui/panel";

const DAYS: [string, string][] = [
  ["mon", "Monday"],
  ["tue", "Tuesday"],
  ["wed", "Wednesday"],
  ["thu", "Thursday"],
  ["fri", "Friday"],
  ["sat", "Saturday"],
  ["sun", "Sunday"],
];
const WORKDAY: DaySpan = { from: "09:00", to: "18:00" };

type Status = { error: string | null; saved?: boolean };

/** Workspace settings → Work hours: one week for the whole workspace (check-in /
 * check-out per day, or OFF) on the owner's clock, and who stays on today. */
export function WorkHoursSettings({
  workspaceId,
  hours,
  titles,
}: {
  workspaceId: string;
  hours: WorkHours | null;
  /** Each agent's name on the page ("" = the Co-Founder). */
  titles: Record<string, string>;
}) {
  if (hours === null)
    return (
      <p className="text-sm text-ink-2">
        The work hours can&apos;t be read right now.
      </p>
    );
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <p className="text-sm text-pretty text-ink-2">
        Like a company: the agents check in and check out at these times. Off
        the clock nothing runs — no new cards, no automations or heartbeats, no
        tokens. An agent in the middle of a card finishes it (2 hours at most,
        then the card waits for the next check-in) and picks up where it
        stopped. Messages you send meanwhile are answered at check-in.
      </p>
      <WeekCard workspaceId={workspaceId} hours={hours} />
      <StayCard workspaceId={workspaceId} hours={hours} titles={titles} />
    </div>
  );
}

function WeekCard({
  workspaceId,
  hours,
}: {
  workspaceId: string;
  hours: WorkHours;
}) {
  const [on, setOn] = useState(hours.on);
  const [days, setDays] = useState<Record<string, DaySpan | null>>(() =>
    Object.fromEntries(DAYS.map(([d]) => [d, hours.days[d] ?? null])),
  );
  const [busy, start] = useTransition();
  const [status, setStatus] = useState<Status>({ error: null });
  const set = (day: string, span: DaySpan | null) => {
    setDays((was) => ({ ...was, [day]: span }));
  };
  return (
    <PanelSection
      aria-labelledby="work-hours-title"
      className="flex flex-col gap-4 p-5"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2
            id="work-hours-title"
            className="font-display text-base font-semibold text-balance"
          >
            Work hours
          </h2>
          <p className="mt-1 text-sm text-ink-2">
            {on
              ? `On your clock (${hours.zone}, Settings → General → Timezone).`
              : "Off: the agents work around the clock, as now."}
          </p>
          {hours.on && (
            <p className="mt-1 text-sm text-ink-3 tabular-nums">
              {hours.checkOut
                ? `Now: on the clock until ${hours.checkOutText}.`
                : hours.nextCheckIn
                  ? `Now: off until ${hours.nextCheckInText}.`
                  : "Now: off (no work day ahead)."}
            </p>
          )}
        </div>
        <Switch
          defaultOn={hours.on}
          label="Use work hours"
          disabled={busy}
          onChange={setOn}
        />
      </div>
      <ul className="flex flex-col divide-y divide-line">
        {DAYS.map(([day, label]) => {
          const span = days[day] ?? null;
          const overnight = span !== null && span.to <= span.from;
          return (
            <li
              key={day}
              className="flex flex-wrap items-center gap-x-3 gap-y-2 py-2.5"
            >
              <span className="w-24 text-sm font-medium text-ink">{label}</span>
              <label className="flex min-h-10 items-center gap-2 text-sm text-ink-2">
                <input
                  type="checkbox"
                  checked={span !== null}
                  disabled={busy}
                  onChange={(e) => {
                    set(day, e.currentTarget.checked ? WORKDAY : null);
                  }}
                />
                Works
              </label>
              {span === null ? (
                <span className="rounded-md bg-sunken px-2 py-0.5 text-xs font-medium text-ink-3">
                  OFF
                </span>
              ) : (
                <span className="flex flex-wrap items-center gap-2 text-sm text-ink-2">
                  <Input
                    type="time"
                    aria-label={`${label} check-in`}
                    value={span.from}
                    disabled={busy}
                    className="w-32 tabular-nums"
                    onChange={(e) => {
                      set(day, { ...span, from: e.currentTarget.value });
                    }}
                  />
                  to
                  <Input
                    type="time"
                    aria-label={`${label} check-out`}
                    value={span.to}
                    disabled={busy}
                    className="w-32 tabular-nums"
                    onChange={(e) => {
                      set(day, { ...span, to: e.currentTarget.value });
                    }}
                  />
                  {overnight && (
                    <span className="text-xs text-ink-3">
                      ends the next morning
                    </span>
                  )}
                </span>
              )}
            </li>
          );
        })}
      </ul>
      <div className="flex items-center gap-3">
        <Button
          variant="primary"
          disabled={busy}
          onClick={() => {
            start(async () => {
              setStatus(await saveWorkHours(workspaceId, { on, days }));
            });
          }}
        >
          Save
        </Button>
        <FormStatus error={status.error} saved={status.saved} />
      </div>
    </PanelSection>
  );
}

function StayCard({
  workspaceId,
  hours,
  titles,
}: {
  workspaceId: string;
  hours: WorkHours;
  titles: Record<string, string>;
}) {
  const [picked, setPicked] = useState<Set<string>>(
    () => new Set(hours.stay ?? []),
  );
  const [busy, start] = useTransition();
  const [status, setStatus] = useState<Status>({ error: null });
  const agents = hours.agents ?? [];
  return (
    <PanelSection
      aria-labelledby="stay-on-title"
      className="flex flex-col gap-4 p-5"
    >
      <div>
        <h2
          id="stay-on-title"
          className="font-display text-base font-semibold text-balance"
        >
          Who stays on today
        </h2>
        <p className="mt-1 text-sm text-pretty text-ink-2">
          They keep working without stopping until the next check-in
          {hours.nextCheckInText ? ` (${hours.nextCheckInText})` : ""}, then
          this clears by itself. Today only.
        </p>
      </div>
      <ul className="flex flex-col gap-1">
        {agents.map((a) => (
          <li key={a.agent}>
            <label className="flex min-h-10 items-center gap-2.5 rounded-lg px-1 text-sm text-ink">
              <input
                type="checkbox"
                checked={picked.has(a.agent)}
                disabled={busy}
                onChange={(e) => {
                  const on = e.currentTarget.checked;
                  setPicked((was) => {
                    const next = new Set(was);
                    if (on) next.add(a.agent);
                    else next.delete(a.agent);
                    return next;
                  });
                }}
              />
              <span className="min-w-0 truncate">
                {titles[a.agent] ?? (a.agent ? `@${a.agent}` : "Co-Founder")}
              </span>
              {a.state && <ShiftChip state={a.state} until={a.untilText} />}
            </label>
          </li>
        ))}
      </ul>
      <div className="flex items-center gap-3">
        <Button
          disabled={busy || !hours.on}
          onClick={() => {
            start(async () => {
              setStatus(await setStayOnToday(workspaceId, [...picked]));
            });
          }}
        >
          Save who stays on
        </Button>
        {!hours.on && (
          <span className="text-xs text-ink-3">
            Turn the work hours on first.
          </span>
        )}
        <FormStatus error={status.error} saved={status.saved} />
      </div>
    </PanelSection>
  );
}
