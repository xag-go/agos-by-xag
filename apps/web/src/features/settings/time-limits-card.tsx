"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import { AllHermesSettingsLink } from "./hermes-settings";
import type { HermesTimeLimits } from "@/data/queries";
import { saveHermesTimeLimits } from "./preferences-actions";
import { PanelSection } from "@/shared/ui/panel";

type Limit = HermesTimeLimits["limits"][number];

/** 90 → "1 min 30 s", 86400 → "24 h", 31536000 → "365 d". */
function readable(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "";
  if (seconds === 86_400) return "24 h";
  const units: [number, string][] = [
    [86_400, "d"],
    [3600, "h"],
    [60, "min"],
    [1, "s"],
  ];
  const parts: string[] = [];
  let rest = Math.round(seconds);
  for (const [size, name] of units) {
    const count = Math.floor(rest / size);
    rest -= count * size;
    if (count) parts.push(`${count} ${name}`);
  }
  return parts.slice(0, 2).join(" ");
}

function shown(limit: Limit, value: number | null): string {
  if (value === null) return "not set";
  if (limit.zeroIsNoLimit ? value <= 0 : value >= limit.noLimitValue)
    return "no limit";
  return `${value} s${readable(value) ? ` (${readable(value)})` : ""}`;
}

type Row = { noLimit: boolean; seconds: string };

/** Every timeout of Hermes, in plain words: Hermes's own settings, read from and
 * saved into Hermes's managed settings (AGOS keeps no copy). */
export function TimeLimitsCard({ limits }: { limits: HermesTimeLimits }) {
  const start: Record<string, Row> = Object.fromEntries(
    limits.limits.map((l) => [
      l.key,
      {
        noLimit: l.noLimit,
        seconds: String(
          l.noLimit || l.value === null
            ? (l.hermesDefault ?? l.noLimitValue)
            : l.value,
        ),
      },
    ]),
  );
  const [rows, setRows] = useState(start);
  const [note, setNote] = useState<string | null>(null);
  const [saving, startSave] = useTransition();

  const valueOf = (l: Limit, row: Row): number =>
    row.noLimit ? l.noLimitValue : Math.round(Number(row.seconds));
  const touched = (l: Limit): boolean => {
    const row = rows[l.key];
    const was = start[l.key];
    return (
      row !== undefined &&
      was !== undefined &&
      (row.noLimit !== was.noLimit ||
        (!row.noLimit && row.seconds !== was.seconds))
    );
  };
  const set = (key: string, change: Partial<Row>) => {
    setRows((now) => {
      const row = now[key];
      return row ? { ...now, [key]: { ...row, ...change } } : now;
    });
    setNote(null);
  };

  const row = (l: Limit) => {
    const r = rows[l.key];
    if (!r) return null;
    const seconds = Number(r.seconds);
    const zeroWarning = !r.noLimit && seconds === 0 && !l.zeroIsNoLimit;
    return (
      <div
        key={l.key}
        className="flex flex-col gap-2 border-t border-line pt-3 first:border-t-0 first:pt-0 sm:flex-row sm:items-start sm:justify-between"
      >
        <div className="min-w-0 flex-1">
          <span className="block text-sm font-medium">{l.label}</span>
          <span className="block text-sm text-ink-2">{l.hint}</span>
          <span className="mt-0.5 block font-mono text-xs text-ink-3">
            {l.key}
            {l.restart && " · applies when the workspace next starts"}
            {!l.readByHermes && " · not read yet (kept for when it is)"}
          </span>
          {l.spread.length > 0 && (
            <span className="mt-1 block text-sm text-warn">
              Workspaces differ:{" "}
              {l.spread
                .map((s) => `${shown(l, s.value)} in ${s.profiles.join(", ")}`)
                .join("; ")}
              . Saving this one sets it the same everywhere.
            </span>
          )}
          {zeroWarning && (
            <span className="mt-1 block text-sm text-warn">
              0 isn&apos;t &quot;no limit&quot; here. Turn on No limit instead.
            </span>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={r.noLimit}
              onChange={(e) => set(l.key, { noLimit: e.target.checked })}
            />
            No limit
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="number"
              min={l.zeroIsNoLimit ? 0 : 1}
              max={31_536_000}
              value={r.noLimit ? String(l.noLimitValue) : r.seconds}
              disabled={r.noLimit}
              aria-label={`${l.label}, seconds`}
              onChange={(e) => set(l.key, { seconds: e.target.value })}
              className="h-9 w-32 rounded-lg border border-line bg-panel px-3 text-sm disabled:opacity-50"
            />
            <span className="w-24 text-ink-2">
              {r.noLimit
                ? l.zeroIsNoLimit
                  ? "seconds (0)"
                  : `s (${readable(l.noLimitValue)})`
                : readable(seconds) || "seconds"}
            </span>
          </label>
        </div>
      </div>
    );
  };

  return (
    <PanelSection id="time-limits" className="scroll-mt-6 p-5">
      <h3 className="font-medium">Time limits</h3>
      <p className="mt-1 text-sm text-ink-2">
        Every clock on the team&apos;s work, one value for every workspace and
        every member ({limits.profiles} profiles), saved once into the shared
        settings, which they all read. No limit is 0 where 0 means no limit, and
        24 hours where it doesn&apos;t (there 0 would stop things at once). New
        workspaces and members use the same values. Which model each helper uses
        is on{" "}
        <Link href="/settings/helper-models" className="underline">
          Helper models
        </Link>
        .
      </p>
      <form
        className="mt-4 flex flex-col gap-6"
        onSubmit={(event) => {
          event.preventDefault();
          const values: Record<string, number> = {};
          for (const l of limits.limits) {
            const r = rows[l.key];
            if (!r || !touched(l)) continue;
            const v = valueOf(l, r);
            if (!Number.isFinite(v) || v < 0) {
              setNote(`${l.label}: use a number of seconds.`);
              return;
            }
            if (v === 0 && !l.zeroIsNoLimit) {
              setNote(`${l.label}: 0 isn't "no limit" here; turn on No limit.`);
              return;
            }
            values[l.key] = v;
          }
          if (!Object.keys(values).length) {
            setNote("Nothing changed.");
            return;
          }
          setNote(null);
          startSave(async () => {
            const r = await saveHermesTimeLimits(values);
            setNote(r.error ?? "Saved.");
          });
        }}
      >
        {limits.groups.map((group) => (
          <fieldset key={group} className="flex flex-col gap-3">
            <legend className="mb-2 text-sm font-semibold">{group}</legend>
            {limits.limits.filter((l) => l.group === group).map(row)}
          </fieldset>
        ))}
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
      <AllHermesSettingsLink search="timeout" />
    </PanelSection>
  );
}
