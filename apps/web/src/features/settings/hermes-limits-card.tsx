"use client";

import { useState, useTransition } from "react";
import type { HermesLimitsShown } from "@/data/queries";
import { saveHermesLimits } from "./preferences-actions";
import { PanelSection } from "@/shared/ui/panel";

const text = (n: number | null | undefined) =>
  n === null || n === undefined ? "" : String(n);
const numberOrNull = (v: string) => (v.trim() === "" ? null : Number(v));

/** The loop detector and the time limit: Hermes's own settings, written into every
 * workspace's Hermes (AGOS keeps no copy, not even of Hermes's defaults: an empty
 * field is Hermes's own default). */
export function HermesLimitsCard({ limits }: { limits: HermesLimitsShown }) {
  const hermes = limits.hermesDefaults;
  const [loopOn, setLoopOn] = useState(limits.loopOn);
  const [sameError, setSameError] = useState(text(limits.sameError));
  const [sameTool, setSameTool] = useState(text(limits.sameToolFailing));
  const [noProgress, setNoProgress] = useState(text(limits.noProgress));
  const [timeOn, setTimeOn] = useState(
    (limits.timeLimitMinutes ?? null) !== null,
  );
  const [minutes, setMinutes] = useState(text(limits.timeLimitMinutes));
  const [ownCap, setOwnCap] = useState((limits.membersAtOnce ?? null) !== null);
  const [atOnce, setAtOnce] = useState(
    text(limits.membersAtOnce ?? hermes.membersAtOnce),
  );
  const [note, setNote] = useState<string | null>(null);
  const [saving, start] = useTransition();

  const number = (
    label: string,
    value: string,
    set: (v: string) => void,
    disabled: boolean,
    min: number,
    max: number,
    placeholder?: number | null,
    required = false,
  ) => (
    <label className="flex flex-col gap-1 text-sm">
      <span className={disabled ? "text-ink-3" : "font-medium"}>{label}</span>
      <input
        type="number"
        min={min}
        max={max}
        value={value}
        placeholder={text(placeholder)}
        required={required && !disabled}
        disabled={disabled}
        onChange={(e) => {
          set(e.target.value);
          setNote(null);
        }}
        className="h-9 w-28 rounded-lg border border-line bg-panel px-3 text-sm disabled:opacity-50"
      />
    </label>
  );

  return (
    <PanelSection id="loop-detector" className="scroll-mt-6 p-5">
      <h3 className="font-medium">
        Loop detector, time limit and members at once
      </h3>
      <p className="mt-1 text-sm text-ink-2">
        Hermes&apos;s own settings, one value for every workspace (tasks, chats,
        Telegram and automations), saved once into Hermes&apos;s managed
        settings, which every workspace reads. An empty number is Hermes&apos;s
        own default (shown in grey).
      </p>
      <form
        className="mt-4 flex flex-col gap-5"
        onSubmit={(event) => {
          event.preventDefault();
          setNote(null);
          start(async () => {
            const r = await saveHermesLimits({
              loopOn,
              sameError: numberOrNull(sameError),
              sameToolFailing: numberOrNull(sameTool),
              noProgress: numberOrNull(noProgress),
              timeLimitMinutes: timeOn ? numberOrNull(minutes) : null,
              membersAtOnce: ownCap ? numberOrNull(atOnce) : null,
            });
            setNote(r.error ?? "Saved in Hermes.");
          });
        }}
      >
        <div className="flex flex-col gap-3">
          <label className="flex items-start gap-3">
            <input
              type="checkbox"
              checked={loopOn}
              onChange={(e) => {
                setLoopOn(e.target.checked);
                setNote(null);
              }}
              className="mt-1"
            />
            <span>
              <span className="block text-sm font-medium">Loop detector</span>
              <span className="block text-sm text-ink-2">
                Hermes always warns the agent when it repeats itself. On: it
                also stops the answer after these many tries. Off: it only
                warns.
              </span>
            </span>
          </label>
          <div className="flex flex-wrap gap-4 pl-7">
            {number(
              "Same error",
              sameError,
              setSameError,
              !loopOn,
              2,
              100,
              hermes.sameError,
            )}
            {number(
              "Same tool failing",
              sameTool,
              setSameTool,
              !loopOn,
              2,
              100,
              hermes.sameToolFailing,
            )}
            {number(
              "Same thing, no progress",
              noProgress,
              setNoProgress,
              !loopOn,
              2,
              100,
              hermes.noProgress,
            )}
          </div>
        </div>

        <div className="flex flex-col gap-3">
          <label className="flex items-start gap-3">
            <input
              type="checkbox"
              checked={timeOn}
              onChange={(e) => {
                setTimeOn(e.target.checked);
                setNote(null);
              }}
              className="mt-1"
            />
            <span>
              <span className="block text-sm font-medium">Time limit</span>
              <span className="block text-sm text-ink-2">
                The longest one answer of an agent can take. At 80% Hermes tells
                it to wrap up; at the limit it stops, and a task that
                wasn&apos;t done shows Blocked with why. Off: no limit.
              </span>
            </span>
          </label>
          <div className="pl-7">
            {number(
              "Minutes",
              minutes,
              setMinutes,
              !timeOn,
              1,
              525600,
              null,
              true,
            )}
          </div>
        </div>

        <div className="flex flex-col gap-3">
          <label className="flex items-start gap-3">
            <input
              type="checkbox"
              checked={ownCap}
              onChange={(e) => {
                setOwnCap(e.target.checked);
                setNote(null);
              }}
              className="mt-1"
            />
            <span>
              <span className="block text-sm font-medium">
                Members working at once
              </span>
              <span className="block text-sm text-ink-2">
                On a workspace&apos;s Kanban, how many team members work on
                cards at the same time. More cards wait their turn
                (Hermes&apos;s own cap, for each workspace).{" "}
                {ownCap
                  ? "On: your number."
                  : (hermes.membersAtOnce ?? null) !== null
                    ? `Off: Hermes decides from this machine's memory (${hermes.membersAtOnce} at once now).`
                    : "Off: Hermes decides from this machine's memory."}
              </span>
            </span>
          </label>
          <div className="pl-7">
            {number(
              "Members",
              atOnce,
              setAtOnce,
              !ownCap,
              1,
              20,
              hermes.membersAtOnce,
              true,
            )}
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={saving}
            className="h-9 rounded-lg bg-accent px-4 text-sm font-medium text-accent-ink disabled:opacity-60"
          >
            Save
          </button>
          {note && <span className="text-sm text-ink-2">{note}</span>}
        </div>
      </form>
    </PanelSection>
  );
}
