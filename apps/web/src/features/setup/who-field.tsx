"use client";

import { useState } from "react";
import type { Automation, LibraryItem } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { Input, Textarea } from "@/shared/ui/field";
import { cn } from "@/shared/ui/cn";

type Step = {
  key: string;
  title: string;
  description: string;
  kind: "work" | "review" | "approval";
  agent: string | null;
  waitsOn: string[];
  reviews: string | null;
};

const stepsOf = (a: Automation | null): Step[] =>
  (a?.steps ?? []).map((s) => ({
    key: s.key,
    title: s.title,
    description: s.description,
    kind: s.kind,
    agent: s.agent ?? null,
    waitsOn: s.waitsOn ?? [],
    reviews: s.reviews ?? null,
  }));
type Mode = "one" | "team";

const blank = (n: number): Step => ({
  key: `s${String(n)}`,
  title: "",
  description: "",
  kind: "work",
  agent: null,
  waitsOn: [],
  reviews: null,
});

const selectClass =
  "h-9 rounded-lg border border-line-strong bg-panel px-2 text-sm text-ink focus:border-accent focus:outline-none";

/** Who does an automation: one member of the team (or the Co-Founder), or a team
 * plan — steps done by different agents one after another. Sent as the hidden
 * fields `agent` and `steps` (JSON). */
export function WhoField({
  automation,
  agents,
}: {
  automation: Automation | null;
  agents: LibraryItem[];
}) {
  const saved = stepsOf(automation);
  const [mode, setMode] = useState<Mode>(saved.length > 0 ? "team" : "one");
  const [agent, setAgent] = useState(automation?.agent ?? "");
  const [steps, setSteps] = useState<Step[]>(
    saved.length > 0 ? saved : [blank(1), { ...blank(2), waitsOn: ["s1"] }],
  );
  const nextKey = () => {
    let n = steps.length + 1;
    while (steps.some((s) => s.key === `s${String(n)}`)) n += 1;
    return n;
  };
  const patch = (i: number, change: Partial<Step>) =>
    setSteps((all) => all.map((s, j) => (j === i ? { ...s, ...change } : s)));
  const remove = (i: number) =>
    setSteps((all) => {
      const gone = all[i]?.key;
      return all
        .filter((_, j) => j !== i)
        .map((s) => ({
          ...s,
          waitsOn: s.waitsOn.filter((w) => w !== gone),
          reviews: s.reviews === gone ? null : s.reviews,
          kind: s.reviews === gone ? "work" : s.kind,
        }));
    });
  const nameOf = (key: string) => {
    const s = steps.find((x) => x.key === key);
    return s?.title || key;
  };

  const payload =
    mode === "team"
      ? steps.map((s) => ({
          ...s,
          title: s.title.trim() || s.key,
          agent: s.agent || null,
        }))
      : [];

  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="mb-1.5 text-sm font-medium">Who does it</legend>
      <input type="hidden" name="agent" value={mode === "one" ? agent : ""} />
      <input type="hidden" name="steps" value={JSON.stringify(payload)} />
      <div className="grid grid-cols-2 gap-2" role="radiogroup">
        {(
          [
            ["one", "One member", "A simple job one role covers"],
            ["team", "The team", "Several agents, one after another"],
          ] as const
        ).map(([value, label, hint]) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={mode === value}
            onClick={() => setMode(value)}
            className={cn(
              "rounded-xl border px-3 py-2 text-left",
              mode === value
                ? "border-accent bg-accent/5"
                : "border-line hover:border-line-strong",
            )}
          >
            <span className="block text-sm font-medium">{label}</span>
            <span className="block text-xs text-ink-3">{hint}</span>
          </button>
        ))}
      </div>

      {mode === "one" ? (
        <div className="flex flex-col gap-1">
          <select
            aria-label="Who does it"
            className={selectClass}
            value={agent}
            onChange={(e) => setAgent(e.target.value)}
          >
            <option value="">Co-Founder</option>
            {agents.map((a) => (
              <option key={a.name} value={a.name}>
                {a.title}
              </option>
            ))}
          </select>
          <p className="text-xs text-ink-3">
            It runs with that agent&apos;s role and instructions. If the agent
            is removed later, the Co-Founder takes over and tells you.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <p className="text-xs text-ink-3">
            At each run these steps go on the Kanban, already approved: each
            agent does its step and hands its result to the next. Steps that
            wait on nothing run at the same time. You get the result at the end.
          </p>
          <ol className="flex flex-col gap-3">
            {steps.map((s, i) => {
              const earlier = steps.slice(0, i);
              return (
                <li
                  key={s.key}
                  className="flex flex-col gap-2 rounded-xl border border-line bg-sunken/40 p-3"
                >
                  <div className="flex items-center gap-2">
                    <span className="w-5 text-sm font-semibold text-ink-3">
                      {i + 1}.
                    </span>
                    <Input
                      aria-label={`Step ${String(i + 1)} title`}
                      value={s.title}
                      placeholder="e.g. 10 ideas per style"
                      onChange={(e) => patch(i, { title: e.target.value })}
                      className="flex-1"
                    />
                    <select
                      aria-label={`Step ${String(i + 1)} done by`}
                      className={selectClass}
                      value={s.agent ?? ""}
                      onChange={(e) =>
                        patch(i, { agent: e.target.value || null })
                      }
                    >
                      <option value="">Co-Founder</option>
                      {agents.map((a) => (
                        <option key={a.name} value={a.name}>
                          {a.title}
                        </option>
                      ))}
                    </select>
                    {steps.length > 1 && (
                      <button
                        type="button"
                        aria-label={`Remove step ${String(i + 1)}`}
                        onClick={() => remove(i)}
                        className="px-1 text-ink-3 hover:text-danger"
                      >
                        ×
                      </button>
                    )}
                  </div>
                  <Textarea
                    aria-label={`Step ${String(i + 1)} details`}
                    rows={2}
                    value={s.description}
                    placeholder="What exactly to do, and what to hand on."
                    onChange={(e) => patch(i, { description: e.target.value })}
                  />
                  {earlier.length > 0 && (
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-2">
                      <span className="text-ink-3">Starts after:</span>
                      {earlier.map((e) => (
                        <label key={e.key} className="flex items-center gap-1">
                          <input
                            type="checkbox"
                            checked={
                              s.waitsOn.includes(e.key) || s.reviews === e.key
                            }
                            disabled={s.reviews === e.key}
                            onChange={(ev) =>
                              patch(i, {
                                waitsOn: ev.target.checked
                                  ? [...s.waitsOn, e.key]
                                  : s.waitsOn.filter((w) => w !== e.key),
                              })
                            }
                          />
                          {nameOf(e.key)}
                        </label>
                      ))}
                      <label className="ml-auto flex items-center gap-1">
                        <span className="text-ink-3">Checks</span>
                        <select
                          aria-label={`Step ${String(i + 1)} checks`}
                          className="h-7 rounded border border-line-strong bg-panel px-1 text-xs"
                          value={s.reviews ?? ""}
                          onChange={(e) =>
                            patch(i, {
                              reviews: e.target.value || null,
                              kind: e.target.value ? "review" : "work",
                            })
                          }
                        >
                          <option value="">nothing</option>
                          {earlier.map((e) => (
                            <option key={e.key} value={e.key}>
                              {nameOf(e.key)}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
          <Button
            type="button"
            variant="ghost"
            className="self-start"
            onClick={() => {
              const n = nextKey();
              const last = steps.at(-1)?.key;
              setSteps((all) => [
                ...all,
                { ...blank(n), waitsOn: last ? [last] : [] },
              ]);
            }}
          >
            + Add a step
          </Button>
          {agents.length === 0 && (
            <p className="text-xs text-attention-ink">
              This project has no agents yet: the Co-Founder does every step.
              Add agents in Hierarchy → Team agents.
            </p>
          )}
        </div>
      )}
    </fieldset>
  );
}
