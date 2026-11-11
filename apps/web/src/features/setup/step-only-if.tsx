"use client";

import type { StepCondition } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { Input, Select } from "@/shared/ui/field";

/** One "Only if" line of a team step as the editor holds it (values as typed). */
export type StepLine =
  | { kind: "match"; field: string; op: MatchOp; values: string }
  | { kind: "check"; check: string };

type MatchOp = NonNullable<StepCondition["op"]>;
type MatchLine = Extract<StepLine, { kind: "match" }>;

const opText: Record<MatchOp, string> = {
  is: "is one of",
  is_not: "is not one of",
  contains: "contains",
  not_contains: "doesn't contain",
};

export const toStepLines = (saved: StepCondition[] | undefined): StepLine[] =>
  (saved ?? []).map((c) =>
    c.check
      ? { kind: "check", check: c.check }
      : {
          kind: "match",
          field: c.field ?? "",
          op: c.op ?? "is",
          values: (c.values ?? []).join(", "),
        },
  );

/** The lines as the core saves them (it checks them for real). */
export const fromStepLines = (lines: StepLine[]): StepCondition[] =>
  lines.map((l) =>
    l.kind === "check"
      ? { check: l.check.trim() }
      : {
          field: l.field.trim(),
          op: l.op,
          values: l.values
            .split(",")
            .map((v) => v.trim())
            .filter(Boolean),
        },
  );

function RemoveLine({ onRemove }: { onRemove: () => void }) {
  return (
    <Button
      variant="ghost"
      aria-label="Remove this line"
      onClick={() => {
        onRemove();
      }}
    >
      Remove
    </Button>
  );
}

function CheckRow({
  label,
  check,
  onChange,
  onRemove,
}: {
  label: string;
  check: string;
  onChange: (check: string) => void;
  onRemove: () => void;
}) {
  return (
    <div className="flex gap-2 rounded-lg border border-line p-2">
      <Input
        aria-label={`${label} check script`}
        className="flex-1"
        value={check}
        placeholder="/workspace/tools/inspiration_gate.py"
        onChange={(e) => {
          onChange(e.target.value);
        }}
      />
      <RemoveLine onRemove={onRemove} />
    </div>
  );
}

function MatchRow({
  label,
  line,
  onChange,
  onRemove,
}: {
  label: string;
  line: MatchLine;
  onChange: (line: MatchLine) => void;
  onRemove: () => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-2 rounded-lg border border-line p-2 sm:grid-cols-2">
      <Input
        aria-label={`${label} field`}
        value={line.field}
        placeholder="payload.sheet"
        onChange={(e) => {
          onChange({ ...line, field: e.target.value });
        }}
      />
      <Select
        aria-label={`${label} test`}
        value={line.op}
        onChange={(e) => {
          onChange({ ...line, op: e.target.value as MatchOp });
        }}
      >
        {Object.entries(opText).map(([op, text]) => (
          <option key={op} value={op}>
            {text}
          </option>
        ))}
      </Select>
      <div className="flex gap-2 sm:col-span-2">
        <Input
          aria-label={`${label} values`}
          className="flex-1"
          value={line.values}
          placeholder="Editing-Inspiration"
          onChange={(e) => {
            onChange({ ...line, values: e.target.value });
          }}
        />
        <RemoveLine onRemove={onRemove} />
      </div>
    </div>
  );
}

/** A team step's "Only if" lines: the step starts its agent only when every line
 * holds; else its card closes as skipped at once, with no tokens spent. Same look
 * as the webhook's Only-if lines. */
export function StepOnlyIf({
  step,
  lines,
  onChange,
}: {
  step: number;
  lines: StepLine[];
  onChange: (lines: StepLine[]) => void;
}) {
  const set = (i: number, line: StepLine) => {
    onChange(lines.map((l, j) => (j === i ? line : l)));
  };
  const drop = (i: number) => () => {
    onChange(lines.filter((_, j) => j !== i));
  };
  const add = (line: StepLine) => () => {
    onChange([...lines, line]);
  };
  const label = `Step ${String(step)}`;

  return (
    <section className="flex flex-col gap-2">
      <div>
        <p className="text-sm font-medium">Only if</p>
        <p className="text-xs text-ink-3">
          The step starts only when every line holds; otherwise it is skipped at
          once (no tokens) and the next steps go on. Field =
          payload.&lt;path&gt; of what the webhook sent (e.g. payload.sheet), or
          a variable. A check is a script in /workspace whose last line says YES
          / AH (run) or NO / LA (skip).
        </p>
      </div>
      {lines.length === 0 && (
        <p className="text-sm text-ink-3">No line: this step always runs.</p>
      )}
      {lines.map((l, i) =>
        l.kind === "check" ? (
          <CheckRow
            key={i}
            label={label}
            check={l.check}
            onChange={(check) => {
              set(i, { kind: "check", check });
            }}
            onRemove={drop(i)}
          />
        ) : (
          <MatchRow
            key={i}
            label={label}
            line={l}
            onChange={(line) => {
              set(i, line);
            }}
            onRemove={drop(i)}
          />
        ),
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="ghost"
          onClick={add({ kind: "match", field: "", op: "is", values: "" })}
        >
          Add a line
        </Button>
        <Button variant="ghost" onClick={add({ kind: "check", check: "" })}>
          Add a check script
        </Button>
      </div>
    </section>
  );
}
