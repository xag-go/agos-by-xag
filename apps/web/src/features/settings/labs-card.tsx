"use client";

import { useState } from "react";
import type { FeatureFlag } from "@/data/queries";
import { Switch } from "@/shared/ui/switch";
import { saveFlag } from "./labs-actions";

/** Settings → General → Labs: one switch per feature flag (core: actions/flags.py).
 * Off is the kill switch. A flag set on this machine (AGOS_FLAG_<NAME>) can't be
 * changed here. */
export function LabsCard({ flags }: { flags: FeatureFlag[] }) {
  const [error, setError] = useState<string | null>(null);
  if (flags.length === 0) {
    return <p className="text-sm text-ink-2">Nothing in Labs right now.</p>;
  }
  return (
    <div className="flex flex-col gap-3">
      <ul className="divide-y divide-line rounded-xl border border-line">
        {flags.map((flag) => (
          <li
            key={flag.name}
            className="flex items-start justify-between gap-4 px-4 py-3"
          >
            <span>
              <span className="block text-sm font-medium">{flag.title}</span>
              <span className="block text-sm text-ink-2">
                {flag.about}
                {flag.forced ? " Set on this machine (AGOS_FLAG_…)." : ""}
              </span>
            </span>
            <Switch
              defaultOn={flag.on}
              label={flag.title}
              disabled={flag.forced}
              onChange={async (on) => {
                setError((await saveFlag(flag.name, on)).error);
              }}
            />
          </li>
        ))}
      </ul>
      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
