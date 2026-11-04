"use client";

import { useState, useTransition } from "react";
import type {
  Automation,
  AutomationRevision,
  AutomationVariable,
  LibraryItem,
  TicketPreset,
} from "@/data/types";
import { Button } from "@/shared/ui/button";
import { Input, Select } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { formatWhen } from "@/shared/format";
import { restoreRevision } from "./actions";

const TYPES = ["text", "number", "boolean", "select", "date"] as const;
type VarType = (typeof TYPES)[number];

type Row = {
  name: string;
  type: VarType;
  default: string;
  options: string;
  label: string;
};

const rowOf = (v: AutomationVariable): Row => ({
  name: v.name,
  type: v.type ?? "text",
  default: v.default ?? "",
  options: (v.options ?? []).join(", "),
  label: v.label ?? "",
});

/** The Variables tab: typed variables written as {name} in the steps, the
 * instructions or the ticket card text. Sent as the hidden field `variables`
 * (JSON); a scheduled run uses the defaults, Run now may ask other values. */
export function VariablesField({
  automation,
}: {
  automation: Automation | null;
}) {
  const [rows, setRows] = useState<Row[]>(
    (automation?.variables ?? []).map(rowOf),
  );
  const patch = (i: number, change: Partial<Row>) =>
    setRows((all) => all.map((r, j) => (j === i ? { ...r, ...change } : r)));
  const serialised = JSON.stringify(
    rows
      .filter((r) => r.name.trim())
      .map((r) => ({
        name: r.name.trim(),
        type: r.type,
        default: r.default,
        options:
          r.type === "select"
            ? r.options
                .split(",")
                .map((o) => o.trim())
                .filter(Boolean)
            : [],
        label: r.label,
      })),
  );
  return (
    <div className="flex flex-col gap-4">
      <input type="hidden" name="variables" value={serialised} />
      <p className="text-sm text-ink-2">
        Write a variable as <code className="font-mono">{"{name}"}</code> in a
        step&apos;s title or text, or in the instructions: each run fills it
        with the value below. Run now can ask you other values. A webhook run
        also fills <code className="font-mono">{"{payload.field.path}"}</code>{" "}
        from what the app sent, and every run{" "}
        <code className="font-mono">{"{run.date}"}</code> /{" "}
        <code className="font-mono">{"{run.time}"}</code>.
      </p>
      {rows.length === 0 && (
        <p className="text-sm text-ink-3">No variables yet.</p>
      )}
      <ul className="flex flex-col gap-3">
        {rows.map((row, i) => (
          <li
            key={i}
            className="grid grid-cols-[1fr_auto] gap-2 rounded-xl border border-line bg-panel p-3"
          >
            <div className="grid gap-2 sm:grid-cols-2">
              <Input
                aria-label="Variable name"
                placeholder="name (a-z, 0-9, _)"
                value={row.name}
                onChange={(e) =>
                  patch(i, {
                    name: e.target.value
                      .toLowerCase()
                      .replace(/[^a-z0-9_]/g, "_"),
                  })
                }
              />
              <Select
                aria-label="Variable type"
                value={row.type}
                onChange={(e) => patch(i, { type: e.target.value as VarType })}
              >
                {TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </Select>
              <Input
                aria-label="Default value"
                placeholder={
                  row.type === "date"
                    ? "default (YYYY-MM-DD)"
                    : row.type === "boolean"
                      ? "yes or no"
                      : "default value"
                }
                value={row.default}
                onChange={(e) => patch(i, { default: e.target.value })}
              />
              {row.type === "select" ? (
                <Input
                  aria-label="Options"
                  placeholder="options, comma separated"
                  value={row.options}
                  onChange={(e) => patch(i, { options: e.target.value })}
                />
              ) : (
                <Input
                  aria-label="Label"
                  placeholder="label shown in Run now (optional)"
                  value={row.label}
                  onChange={(e) => patch(i, { label: e.target.value })}
                />
              )}
            </div>
            <Button
              type="button"
              variant="ghost"
              aria-label="Remove variable"
              onClick={() => setRows((all) => all.filter((_, j) => j !== i))}
            >
              ×
            </Button>
          </li>
        ))}
      </ul>
      <Button
        type="button"
        className="self-start"
        onClick={() =>
          setRows((all) => [
            ...all,
            { name: "", type: "text", default: "", options: "", label: "" },
          ])
        }
      >
        Add a variable
      </Button>
    </div>
  );
}

const POLICIES = [
  {
    id: "skip_if_active",
    title: "Skip while the last run is still open",
    text: "The default. A trigger while the last run's cards are still on the Kanban does nothing (Hermes already skips an overlapping run).",
  },
  {
    id: "coalesce_if_active",
    title: "Note it on the open cards",
    text: "No new cards: the open cards get one comment “triggered again at <time>”, so the team knows and nothing is lost.",
  },
  {
    id: "always_enqueue",
    title: "Always make new cards",
    text: "Every trigger makes its run's cards; they wait on the previous run's last cards, so runs go one after another.",
  },
] as const;

/** The Policy tab: what a trigger does while the last run's cards are open. */
export function PolicyField({ automation }: { automation: Automation | null }) {
  const [policy, setPolicy] = useState<string>(
    automation?.policy ?? "skip_if_active",
  );
  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="sr-only">Policy while the last run is open</legend>
      <input type="hidden" name="policy" value={policy} />
      {POLICIES.map((p) => (
        <label
          key={p.id}
          className="flex cursor-pointer items-start gap-3 rounded-xl border border-line bg-panel p-3"
        >
          <input
            type="radio"
            name="policy-choice"
            className="mt-1"
            checked={policy === p.id}
            onChange={() => setPolicy(p.id)}
          />
          <span>
            <span className="block text-sm font-medium">{p.title}</span>
            <span className="block text-xs text-ink-3">{p.text}</span>
          </span>
        </label>
      ))}
    </fieldset>
  );
}

/** The Revisions tab: every saved version, newest first, with its diff; Restore
 * is a new save from that version (recorded as “restored from vN”). */
export function RevisionsTab({
  workspaceId,
  automationId,
  revisions,
}: {
  workspaceId: string;
  automationId: number;
  revisions: AutomationRevision[];
}) {
  const [busy, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  if (revisions.length === 0)
    return <p className="text-sm text-ink-3">No saved versions yet.</p>;
  return (
    <ol className="flex flex-col gap-3">
      <FormStatus error={error} />
      {revisions.map((rev, i) => (
        <li key={rev.n} className="rounded-xl border border-line bg-panel p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-ink-3">v{rev.n}</span>
            <span className="text-sm font-medium">{rev.summary}</span>
            <span className="text-xs text-ink-3">
              · {rev.who === "cofounder" ? "Co-Founder" : "you"} ·{" "}
              {formatWhen(rev.at)}
            </span>
            {i > 0 && (
              <Button
                type="button"
                className="ml-auto h-8"
                disabled={busy}
                onClick={() => {
                  setError(null);
                  start(async () => {
                    const r = await restoreRevision(
                      workspaceId,
                      automationId,
                      rev.n,
                    );
                    if (r.error) setError(r.error);
                  });
                }}
              >
                Restore
              </Button>
            )}
          </div>
          {(rev.changes ?? []).length > 0 && (
            <ul className="mt-2 flex flex-col gap-1 text-xs">
              {(rev.changes ?? []).map((c) => (
                <li key={c.field} className="grid grid-cols-[7rem_1fr] gap-2">
                  <span className="text-ink-3">
                    {c.field.replace("_", " ")}
                  </span>
                  <span className="min-w-0 break-words">
                    <span className="text-danger line-through">{c.before}</span>{" "}
                    <span className="text-success">{c.after}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ol>
  );
}

/** The Tickets tab: a ticket on-ramp preset (Linear / Jira / Asana / GitHub).
 * Choosing one fills the webhook's filters and the card text on save; sent as
 * `ticketSource`, `ticketMember` and `ticketStep` (the preset's step, JSON). */
export function TicketPresetField({
  automation,
  presets,
  agents,
}: {
  automation: Automation | null;
  presets: TicketPreset[];
  agents: LibraryItem[];
}) {
  const [source, setSource] = useState(automation?.ticket?.source ?? "");
  const [member, setMember] = useState(automation?.ticket?.member ?? "");
  const preset = presets.find((p) => p.source === source);
  return (
    <div className="flex flex-col gap-4">
      <input type="hidden" name="ticketSource" value={source} />
      <input type="hidden" name="ticketMember" value={member} />
      <input
        type="hidden"
        name="ticketStep"
        value={
          preset
            ? JSON.stringify({ ...preset.step, agent: member || null })
            : ""
        }
      />
      <p className="text-sm text-ink-2">
        Bring your tickets in: each issue the app sends becomes one card on the
        Board (never twice: the card is keyed by the issue), given to the member
        you pick; closing the issue upstream completes the card. The automation
        must be started by a webhook (Start). Nothing is written back to the
        ticket system yet.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-medium">Ticket system</span>
          <Select value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="">None</option>
            {presets.map((p) => (
              <option key={p.source} value={p.source}>
                {p.label}
              </option>
            ))}
          </Select>
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-medium">Who works the issues</span>
          <Select
            value={member}
            disabled={!source}
            onChange={(e) => setMember(e.target.value)}
          >
            <option value="">Co-Founder</option>
            {agents.map((a) => (
              <option key={a.name} value={a.name}>
                {a.title} (@{a.name})
              </option>
            ))}
          </Select>
        </label>
      </div>
      {preset && (
        <div className="rounded-xl border border-line bg-sunken p-3 text-xs text-ink-2">
          <p>
            {preset.signed
              ? `${preset.label} signs every delivery: paste the webhook's signing secret in Webhook → Signing secret.`
              : `${preset.label} can't sign for Hermes: the long webhook address is the check. A relay that can add a header may send the secret as X-Gitlab-Token.`}
          </p>
          <p className="mt-1">
            Filters:{" "}
            {preset.events.length > 0
              ? `events ${preset.events.join(", ")}`
              : preset.conditions.length > 0
                ? preset.conditions
                    .map(
                      (c) =>
                        `${String(c.field)} is ${(c.values as string[]).join(" / ")}`,
                    )
                    .join("; ")
                : "none"}
            . Card key: agos-ticket:{preset.source}:&lt;issue id&gt;.
          </p>
        </div>
      )}
    </div>
  );
}
