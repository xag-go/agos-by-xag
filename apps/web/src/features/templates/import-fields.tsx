"use client";

import Link from "next/link";
import type { BundleInput, ImportReport } from "@/data/types";
import { Field, Input, Select } from "@/shared/ui/field";
import type { Strategies, Strategy } from "./actions";

export const DEFAULT_STRATEGIES: Strategies = {
  agents: "rename",
  skills: "skip",
  automations: "rename",
  vision: "skip",
};

const STRATEGY_WORDS: Record<Strategy, string> = {
  skip: "Keep mine (skip)",
  rename: "Add a copy (rename)",
  replace: "Replace mine",
};

/** One select per kind: what to do when the workspace has one with that name. */
export function StrategyFields({
  value,
  onChange,
  kinds,
}: {
  value: Strategies;
  onChange: (next: Strategies) => void;
  kinds: (keyof Strategies)[];
}) {
  const label: Record<keyof Strategies, string> = {
    agents: "Members with the same name",
    skills: "Skills with the same name",
    automations: "Automations with the same name",
    vision: "This workspace's Vision",
  };
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {kinds.map((kind) => (
        <Field key={kind} label={label[kind]}>
          <Select
            value={value[kind]}
            onChange={(e) => {
              onChange({ ...value, [kind]: e.target.value as Strategy });
            }}
          >
            {(kind === "vision"
              ? (["skip", "replace"] as Strategy[])
              : (["skip", "rename", "replace"] as Strategy[])
            ).map((s) => (
              <option key={s} value={s}>
                {kind === "vision" && s === "replace"
                  ? "Replace it, add the goals"
                  : STRATEGY_WORDS[s]}
              </option>
            ))}
          </Select>
        </Field>
      ))}
    </div>
  );
}

/** The keys the team needs: typed once here (never shown again), or later in
 * Workspace → Keys. Connectors are only listed: he signs in to them himself. */
export function InputFields({
  inputs,
  values,
  later,
  onValues,
  onLater,
}: {
  inputs: BundleInput[];
  values: Record<string, string>;
  later: string[];
  onValues: (next: Record<string, string>) => void;
  onLater: (next: string[]) => void;
}) {
  const keys = inputs.filter((i) => i.kind === "tool_key");
  const connectors = inputs.filter((i) => i.kind !== "tool_key");
  if (inputs.length === 0) return null;
  return (
    <div className="flex flex-col gap-3">
      {keys.map((i) => (
        <div
          key={i.name}
          className="grid items-end gap-2 sm:grid-cols-[1fr_auto]"
        >
          <Field
            label={`${i.name}${i.required ? "" : " (optional)"}`}
            hint={i.description}
          >
            <Input
              type="password"
              autoComplete="off"
              value={values[i.name] ?? ""}
              disabled={later.includes(i.name)}
              onChange={(e) => {
                onValues({ ...values, [i.name]: e.target.value });
              }}
            />
          </Field>
          <label className="flex h-9 items-center gap-2 text-sm text-ink-2">
            <input
              type="checkbox"
              className="size-4 accent-majorelle"
              checked={later.includes(i.name)}
              onChange={(e) => {
                onLater(
                  e.target.checked
                    ? [...later, i.name]
                    : later.filter((n) => n !== i.name),
                );
              }}
            />
            Add later
          </label>
        </div>
      ))}
      {connectors.length > 0 && (
        <p className="text-sm text-ink-2">
          Connectors to sign in to afterwards:{" "}
          {connectors.map((c) => c.app).join(", ")}.
        </p>
      )}
    </div>
  );
}

/** Required keys he neither typed nor put off (the core refuses those too). */
export function missingInputs(
  inputs: BundleInput[],
  values: Record<string, string>,
  later: string[],
): string[] {
  return inputs
    .filter(
      (i) =>
        i.kind === "tool_key" &&
        i.required &&
        !(values[i.name] ?? "").trim() &&
        !later.includes(i.name),
    )
    .map((i) => i.name);
}

const RESULT_WORDS: Record<string, string> = {
  created: "added",
  renamed: "added as",
  replaced: "replaced",
  skipped: "kept yours",
  failed: "not added",
};

/** The fidelity report: what came in (as what), what needs the owner. */
export function ImportReportView({
  report,
  openLink = false,
}: {
  report: ImportReport;
  openLink?: boolean;
}) {
  const failed = report.items.filter((i) => i.result === "failed");
  return (
    <div className="flex flex-col gap-4 text-sm">
      <ul className="flex flex-col gap-1">
        {report.items.map((i) => (
          <li key={`${i.kind}:${i.name}`} className="flex flex-wrap gap-1.5">
            <span className="w-24 text-ink-3">{i.kind}</span>
            <span className="font-medium">{i.name}</span>
            <span
              className={i.result === "failed" ? "text-danger" : "text-ink-2"}
            >
              {RESULT_WORDS[i.result] ?? i.result}
              {i.result === "renamed" ? ` ${i.asName}` : ""}
            </span>
            {i.detail && <span className="text-ink-3">— {i.detail}</span>}
          </li>
        ))}
      </ul>
      {(report.needsOwner.length > 0 || report.problems.length > 0) && (
        <div className="rounded-xl border border-line bg-sunken p-3">
          <p className="mb-1 font-medium">Needs you</p>
          <ul className="list-disc pl-5 text-ink-2">
            {report.problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
            {report.needsOwner.map((n) => (
              <li key={`${n.kind}:${n.name}`}>{n.text}</li>
            ))}
          </ul>
        </div>
      )}
      <p className="text-xs text-ink-3">
        Never carried: {report.notCarried.join("; ")}.
      </p>
      {failed.length === 0 && openLink && (
        <Link
          href={`/w/${report.workspaceId}/hierarchy`}
          className="font-medium text-accent underline"
        >
          Open the workspace&apos;s team
        </Link>
      )}
    </div>
  );
}

/** A file's bytes as base64 (what the core takes for a bundle). */
export async function fileBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}
