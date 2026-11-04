"use client";

import { useState, useTransition } from "react";
import type { BrainMethod } from "@/data/queries";
import { Switch } from "@/shared/ui/switch";
import { setMethodHere } from "@/features/settings/owner-rules-actions";
import { Panel } from "@/shared/ui/panel";

/** The AGOS Brain's methods in one workspace: each one On, or "Not here". */
export function BrainHere({
  workspaceId,
  methods,
}: {
  workspaceId: string;
  methods: BrainMethod[];
}) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  return (
    <section className="flex flex-col gap-3">
      <div>
        <h2 className="font-display text-base font-semibold">
          From the AGOS Brain
        </h2>
        <p className="mt-1 max-w-2xl text-sm text-ink-2">
          Ways of working the whole team learned, shared by every project
          (Settings → Brain). Turn one off if it doesn&apos;t fit this project.
        </p>
      </div>
      {methods.length === 0 ? (
        <p className="text-sm text-ink-3">
          No method yet. Add one in Settings → Brain, or a Co-Founder proposes
          one when a lesson worked more than once.
        </p>
      ) : (
        <Panel as="ul" className="divide-y divide-line">
          {methods.map((m) => (
            <li key={m.id} className="flex items-start gap-4 px-5 py-3">
              <p
                className={
                  m.usedHere
                    ? "flex-1 text-sm whitespace-pre-wrap text-ink"
                    : "flex-1 text-sm whitespace-pre-wrap text-ink-3 line-through"
                }
              >
                {m.text}
              </p>
              <label className="flex shrink-0 items-center gap-2 text-xs text-ink-2">
                {m.usedHere ? "Used here" : "Not here"}
                <Switch
                  defaultOn={m.usedHere}
                  disabled={pending}
                  label={`Use “${m.text.slice(0, 40)}” in this workspace`}
                  onChange={(on) => {
                    setError(null);
                    start(async () => {
                      const r = await setMethodHere(workspaceId, m.id, on);
                      if (r.error) setError(r.error);
                    });
                  }}
                />
              </label>
            </li>
          ))}
        </Panel>
      )}
      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}
    </section>
  );
}
