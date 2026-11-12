"use client";

/** What a team step changes when its waits or its review change. */
export type StepAfterChange = {
  waitsOn?: string[];
  reviews?: string | null;
  kind?: "work" | "review";
};

/** A team step's "Starts after" boxes (the earlier steps it waits on) and the step
 * it checks, if it is a review. */
export function StepAfter({
  step,
  earlier,
  waitsOn,
  reviews,
  nameOf,
  onChange,
}: {
  step: number;
  /** The keys of the steps before this one. */
  earlier: string[];
  waitsOn: string[];
  reviews: string | null;
  nameOf: (key: string) => string;
  onChange: (change: StepAfterChange) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-2">
      <span className="text-ink-3">Starts after:</span>
      {earlier.map((key) => (
        <label key={key} className="flex items-center gap-1">
          <input
            type="checkbox"
            checked={waitsOn.includes(key) || reviews === key}
            disabled={reviews === key}
            onChange={(ev) =>
              onChange({
                waitsOn: ev.target.checked
                  ? [...waitsOn, key]
                  : waitsOn.filter((w) => w !== key),
              })
            }
          />
          {nameOf(key)}
        </label>
      ))}
      <label className="ml-auto flex items-center gap-1">
        <span className="text-ink-3">Checks</span>
        <select
          aria-label={`Step ${String(step)} checks`}
          className="h-7 rounded border border-line-strong bg-panel px-1 text-xs"
          value={reviews ?? ""}
          onChange={(e) =>
            onChange({
              reviews: e.target.value || null,
              kind: e.target.value ? "review" : "work",
            })
          }
        >
          <option value="">nothing</option>
          {earlier.map((key) => (
            <option key={key} value={key}>
              {nameOf(key)}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
