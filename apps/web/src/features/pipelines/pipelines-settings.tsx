"use client";

import { useState, useTransition } from "react";
import type { PipelineRule } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { Field, Input, Select, Textarea } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { Switch } from "@/shared/ui/switch";
import {
  deletePipelineRule,
  savePipelineRule,
  type RuleFields,
} from "./actions";
import { Panel } from "@/shared/ui/panel";

type Option = { value: string; label: string };

const TRIGGERS: Option[] = [
  { value: "status", label: "A card moves to a column" },
  { value: "review_approved", label: "A review stage approves a card" },
  { value: "plan_accepted", label: "A card's plan is accepted" },
];

const ACTIONS: Option[] = [
  { value: "follow_up", label: "Make a follow-up card for a member" },
  { value: "comment", label: "Comment on the card" },
  { value: "assign", label: "Give the card to a member" },
  { value: "run_automation", label: "Run an automation now" },
  { value: "notify", label: "Tell me (chat and phone)" },
];

const EMPTY: RuleFields = {
  name: "",
  trigger: "status",
  status: "done",
  goalId: null,
  label: "",
  action: "follow_up",
  member: "",
  automationId: null,
  text: "",
  enabled: true,
};

function says(rule: RuleFields, opts: Lists): string {
  const when =
    rule.trigger === "status"
      ? `a card moves to ${opts.columns.find((c) => c.value === rule.status)?.label ?? rule.status}`
      : rule.trigger === "review_approved"
        ? "a review stage approves a card"
        : "a card's plan is accepted";
  const scope = [
    rule.goalId !== null &&
      `in ${opts.goals.find((g) => g.value === String(rule.goalId))?.label ?? "a project"}`,
    rule.label && `with #${rule.label}`,
  ]
    .filter(Boolean)
    .join(" ");
  const member =
    opts.members.find((m) => m.value === rule.member)?.label ?? rule.member;
  const what = {
    follow_up: `make a follow-up card for ${member}`,
    comment: "comment on it",
    assign: `give it to ${member}`,
    run_automation: `run ${opts.automations.find((a) => a.value === String(rule.automationId))?.label ?? "an automation"}`,
    notify: "tell you",
  }[rule.action];
  return `When ${when}${scope ? ` ${scope}` : ""}: ${what}.`;
}

type Lists = {
  columns: Option[];
  members: Option[];
  goals: Option[];
  automations: Option[];
};

/** Automations → Rules: "when a card moves to X (in project Y / with #label),
 * do Z". The card, its moves and what a rule makes stay on Hermes's Kanban. */
export function PipelinesSettings({
  workspaceId,
  rules,
  lists,
}: {
  workspaceId: string;
  rules: PipelineRule[];
  lists: Lists;
}) {
  const [editing, setEditing] = useState<number | "new" | null>(null);
  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <div>
        <h2 className="font-display text-xl font-semibold">Rules</h2>
        <p className="mt-1 max-w-2xl text-sm text-ink-2">
          What happens by itself when a card moves on the Kanban: a follow-up
          card for the next member, a comment, an assignment, an automation, or
          a note to you. Each rule acts once per move. Write {"{title}"} or{" "}
          {"{card}"} in the text to name the card.
        </p>
      </div>
      {rules.length === 0 && editing !== "new" && (
        <p className="text-sm text-ink-3">No rules yet.</p>
      )}
      {rules.map((rule) =>
        editing === rule.id ? (
          <RuleForm
            key={rule.id}
            workspaceId={workspaceId}
            ruleId={rule.id}
            initial={rule}
            lists={lists}
            onDone={() => {
              setEditing(null);
            }}
          />
        ) : (
          <RuleRow
            key={rule.id}
            workspaceId={workspaceId}
            rule={rule}
            lists={lists}
            onEdit={() => {
              setEditing(rule.id);
            }}
          />
        ),
      )}
      {editing === "new" ? (
        <RuleForm
          workspaceId={workspaceId}
          ruleId={null}
          initial={{ ...EMPTY, member: lists.members[0]?.value ?? "" }}
          lists={lists}
          onDone={() => {
            setEditing(null);
          }}
        />
      ) : (
        <div>
          <Button
            variant="primary"
            onClick={() => {
              setEditing("new");
            }}
          >
            New rule
          </Button>
        </div>
      )}
    </div>
  );
}

function RuleRow({
  workspaceId,
  rule,
  lists,
  onEdit,
}: {
  workspaceId: string;
  rule: PipelineRule;
  lists: Lists;
  onEdit: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  return (
    <Panel as="article" className="flex flex-col gap-2 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">{rule.name || "A rule"}</h3>
          <p className="text-sm text-ink-2">{says(rule, lists)}</p>
          {rule.lastFiredAt && (
            <p className="mt-1 text-xs text-ink-3">
              Last: {new Date(rule.lastFiredAt).toLocaleString()} ·{" "}
              {rule.lastOutcome}
            </p>
          )}
        </div>
        <Switch
          defaultOn={rule.enabled}
          label="Rule on"
          disabled={busy}
          onChange={(on) => {
            start(async () => {
              const result = await savePipelineRule(workspaceId, rule.id, {
                ...rule,
                enabled: on,
              });
              setError(result.error);
            });
          }}
        />
      </div>
      <div className="flex items-center gap-2">
        <Button variant="ghost" onClick={onEdit} disabled={busy}>
          Edit
        </Button>
        <Button
          variant="ghost"
          disabled={busy}
          onClick={() => {
            start(async () => {
              const result = await deletePipelineRule(workspaceId, rule.id);
              setError(result.error);
            });
          }}
        >
          Delete
        </Button>
        <FormStatus error={error} />
      </div>
    </Panel>
  );
}

function RuleForm({
  workspaceId,
  ruleId,
  initial,
  lists,
  onDone,
}: {
  workspaceId: string;
  ruleId: number | null;
  initial: RuleFields;
  lists: Lists;
  onDone: () => void;
}) {
  const [rule, setRule] = useState<RuleFields>(initial);
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  const set = (changes: Partial<RuleFields>) => {
    setRule((r) => ({ ...r, ...changes }));
  };
  const needsMember = rule.action === "follow_up" || rule.action === "assign";
  const needsText = ["follow_up", "comment", "notify"].includes(rule.action);
  return (
    <form
      className="flex flex-col gap-3 rounded-2xl border border-line-strong bg-panel p-5"
      onSubmit={(event) => {
        event.preventDefault();
        start(async () => {
          const result = await savePipelineRule(workspaceId, ruleId, rule);
          setError(result.error);
          if (!result.error) onDone();
        });
      }}
    >
      <Field label="Name">
        <Input
          value={rule.name}
          maxLength={120}
          placeholder="Recap after each launch"
          onChange={(e) => {
            set({ name: e.currentTarget.value });
          }}
        />
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="When">
          <Select
            value={rule.trigger}
            onChange={(e) => {
              set({ trigger: e.currentTarget.value as RuleFields["trigger"] });
            }}
          >
            {TRIGGERS.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </Select>
        </Field>
        {rule.trigger === "status" && (
          <Field label="Column">
            <Select
              value={rule.status}
              onChange={(e) => {
                set({ status: e.currentTarget.value });
              }}
            >
              {lists.columns.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </Select>
          </Field>
        )}
        <Field label="Only in (goal or project)">
          <Select
            value={rule.goalId === null ? "" : String(rule.goalId)}
            onChange={(e) => {
              const v = e.currentTarget.value;
              set({ goalId: v ? Number(v) : null });
            }}
          >
            <option value="">Any card</option>
            {lists.goals.map((g) => (
              <option key={g.value} value={g.value}>
                {g.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Only with label">
          <Input
            value={rule.label}
            maxLength={41}
            placeholder="#launch (in the card's title or text)"
            onChange={(e) => {
              set({ label: e.currentTarget.value });
            }}
          />
        </Field>
        <Field label="Do">
          <Select
            value={rule.action}
            onChange={(e) => {
              set({ action: e.currentTarget.value as RuleFields["action"] });
            }}
          >
            {ACTIONS.map((a) => (
              <option key={a.value} value={a.value}>
                {a.label}
              </option>
            ))}
          </Select>
        </Field>
        {needsMember && (
          <Field label="Member">
            <Select
              value={rule.member}
              onChange={(e) => {
                set({ member: e.currentTarget.value });
              }}
            >
              {lists.members.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </Select>
          </Field>
        )}
        {rule.action === "run_automation" && (
          <Field label="Automation">
            <Select
              value={
                rule.automationId === null ? "" : String(rule.automationId)
              }
              onChange={(e) => {
                const v = e.currentTarget.value;
                set({ automationId: v ? Number(v) : null });
              }}
            >
              <option value="">Pick one</option>
              {lists.automations.map((a) => (
                <option key={a.value} value={a.value}>
                  {a.label}
                </option>
              ))}
            </Select>
          </Field>
        )}
      </div>
      {needsText && (
        <Field
          label={
            rule.action === "follow_up"
              ? "The follow-up card (first line = its title)"
              : rule.action === "comment"
                ? "The comment"
                : "The note"
          }
        >
          <Textarea
            rows={3}
            value={rule.text}
            maxLength={4000}
            onChange={(e) => {
              set({ text: e.currentTarget.value });
            }}
          />
        </Field>
      )}
      <p className="text-sm text-ink-3">{says(rule, lists)}</p>
      <div className="flex items-center gap-2">
        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? "Saving…" : "Save rule"}
        </Button>
        <Button variant="ghost" onClick={onDone} disabled={busy}>
          Cancel
        </Button>
        <FormStatus error={error} />
      </div>
    </form>
  );
}
