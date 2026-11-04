"use client";

import type { Proposal } from "@/data/types";
import { Select } from "@/shared/ui/field";

/** A hire's model as the proposal carries it (null: the workspace's model). */
export type HireModel = {
  provider?: string;
  mode?: string;
  model?: string;
  effort?: string;
} | null;

type Choices = NonNullable<Proposal["modelChoices"]>;
type Choice = Choices["models"][number];

/** Claude's families, smallest first, in the owner's words. */
const FAMILIES: { id: string; label: string }[] = [
  { id: "haiku", label: "Haiku · small, repetitive work" },
  { id: "sonnet", label: "Sonnet · everyday work" },
  { id: "opus", label: "Opus · deep work" },
];
const EFFORT_WORDS: Record<string, string> = {
  minimal: "Minimal",
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "Extra high",
  max: "Max",
  none: "Off",
  standard: "Standard",
};

/** a family-major-minor id → [major, minor]; a date suffix counts last (as the core's rule). */
function version(id: string): number[] {
  const date = /-(\d{8})$/.exec(id);
  const head = id.replace(/-(\d{8})$/, "");
  return [
    ...(head.match(/\d+/g) ?? []).map(Number),
    date ? Number(date[1]) : 0,
  ];
}

function newer(a: Choice, b: Choice): number {
  const x = version(a.id);
  const y = version(b.id);
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    const d = (y[i] ?? 0) - (x[i] ?? 0);
    if (d !== 0) return d;
  }
  return 0;
}

/** The model shown in one line: "Claude Haiku 4.5 · low". */
export function modelLine(
  model: HireModel | undefined,
  choices: Choices | null | undefined,
): string {
  if (!model?.model) return "";
  const found = choices?.models.find((m) => m.id === model.model);
  const name = found?.label ?? model.model;
  const effort = model.effort ?? "";
  if (!effort || effort === "standard" || effort === "default") return name;
  return `${name} · ${effort === "none" ? "no reasoning" : effort}`;
}

/**
 * The owner's pick for the member's model before Approve: family, version (from
 * Hermes's catalog, the workspace's provider only) and reasoning effort. A new
 * member always has its own (the core refuses a hire without it).
 */
export function ModelPicker({
  choices,
  value,
  onChange,
}: {
  choices: Choices;
  value: HireModel;
  onChange: (next: HireModel) => void;
}) {
  const empty = "Pick its model (required)";
  const models = choices.models;
  const current = models.find((m) => m.id === value?.model) ?? null;
  const families = FAMILIES.filter((f) =>
    models.some((m) => m.family === f.id),
  );
  const grouped = families.length > 0;
  const family = current?.family ?? "";
  const versions = grouped
    ? models.filter((m) => m.family === family).sort(newer)
    : models;

  const pick = (m: Choice | null) => {
    if (!m) {
      onChange(null);
      return;
    }
    const keep = value?.effort && m.efforts.includes(value.effort);
    onChange({
      provider: choices.provider,
      mode: value?.mode,
      model: m.id,
      effort: keep ? value.effort : m.defaultEffort || m.efforts[0],
    });
  };
  const efforts = current?.efforts ?? [];

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {grouped ? (
        <>
          <Select
            aria-label="Model family"
            className="w-60"
            value={family}
            onChange={(e) => {
              const next = models
                .filter((m) => m.family === e.target.value)
                .sort(newer)[0];
              pick(next ?? null);
            }}
          >
            <option value="">{empty}</option>
            {families.map((f) => (
              <option key={f.id} value={f.id}>
                {f.label}
              </option>
            ))}
          </Select>
          {current && (
            <Select
              aria-label="Version"
              className="w-48"
              value={current.id}
              onChange={(e) => {
                pick(models.find((m) => m.id === e.target.value) ?? null);
              }}
            >
              {versions.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </Select>
          )}
        </>
      ) : (
        <Select
          aria-label="Model"
          className="w-64"
          value={current?.id ?? ""}
          onChange={(e) => {
            pick(models.find((m) => m.id === e.target.value) ?? null);
          }}
        >
          <option value="">{empty}</option>
          {models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
            </option>
          ))}
        </Select>
      )}
      {current && efforts.length > 0 && (
        <Select
          aria-label="Reasoning effort"
          className="w-36"
          value={value?.effort ?? current.defaultEffort}
          disabled={efforts.length === 1}
          onChange={(e) => {
            onChange({ ...value, effort: e.target.value });
          }}
        >
          {efforts.map((x) => (
            <option key={x} value={x}>
              {EFFORT_WORDS[x] ?? x}
              {x === "none" ? " (no reasoning)" : ""}
            </option>
          ))}
        </Select>
      )}
      {value?.model && !current && (
        <span className="text-sm text-danger">
          {value.model} isn&apos;t offered to this workspace now: pick another.
        </span>
      )}
    </div>
  );
}
