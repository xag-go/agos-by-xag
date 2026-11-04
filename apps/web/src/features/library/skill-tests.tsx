"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import type {
  KanbanMember,
  SkillTestInput,
  SkillTestRun,
  SkillTests,
} from "@/data/types";
import { Button } from "@/shared/ui/button";
import { Field, Input, Select, Textarea } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import {
  addSkillTestInput,
  deleteSkillTestInput,
  gradeSkillTest,
  readSkillTests,
  rerunSkillTest,
  runSkillTest,
  saveSkillTestSettings,
  updateSkillTestInput,
} from "./skill-studio-actions";
import { when } from "./skill-versions";

// ---- Tests ---------------------------------------------------------------------------

export function TestsTab({
  workspaceId,
  itemId,
  initial,
  members,
}: {
  workspaceId: string;
  itemId: number;
  initial: SkillTests;
  members: KanbanMember[];
}) {
  const [tests, setTests] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  const [member, setMember] = useState(members[0]?.name ?? "cofounder");

  function reload() {
    start(async () => {
      setTests(await readSkillTests(workspaceId, itemId));
    });
  }

  function act(fn: () => Promise<{ error: string | null }>) {
    setError(null);
    start(async () => {
      const result = await fn();
      if (result.error) setError(result.error);
      setTests(await readSkillTests(workspaceId, itemId));
    });
  }

  return (
    <div className="flex flex-col gap-6">
      <p className="text-sm text-ink-2">
        A test run is a card on this workspace&apos;s Kanban: the member runs
        the skill (version {tests.version} now) on a saved input; the
        card&apos;s result comes back here and, with an expected output or a
        checklist, Hermes&apos;s helper model grades it.
      </p>
      <TemplateForm workspaceId={workspaceId} itemId={itemId} tests={tests} />
      <section className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold">Inputs</h3>
        {tests.inputs.length === 0 && (
          <p className="text-sm text-ink-3">No saved input yet.</p>
        )}
        {tests.inputs.map((input) => (
          <InputRow
            key={input.id}
            input={input}
            busy={busy}
            onRun={() =>
              act(() => runSkillTest(workspaceId, itemId, input.id, member))
            }
            onSave={(draft) =>
              act(() =>
                updateSkillTestInput(workspaceId, itemId, input.id, draft),
              )
            }
            onDelete={() =>
              act(() => deleteSkillTestInput(workspaceId, itemId, input.id))
            }
          />
        ))}
        <NewInput
          busy={busy}
          onAdd={(draft) =>
            act(() => addSkillTestInput(workspaceId, itemId, draft))
          }
        />
        <Field label="Run as" className="max-w-xs">
          <Select value={member} onChange={(e) => setMember(e.target.value)}>
            {members.map((m) => (
              <option key={m.name} value={m.name}>
                {m.title}
              </option>
            ))}
          </Select>
        </Field>
        <FormStatus error={error} />
      </section>
      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">Runs</h3>
          <button
            type="button"
            className="text-sm text-ink-2 hover:text-ink"
            disabled={busy}
            onClick={reload}
          >
            Refresh
          </button>
        </div>
        {tests.runs.length === 0 ? (
          <p className="text-sm text-ink-3">No run yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-ink-3">
              <tr>
                <th className="py-1 pr-3 font-medium">Input</th>
                <th className="py-1 pr-3 font-medium">Version</th>
                <th className="py-1 pr-3 font-medium">Card</th>
                <th className="py-1 pr-3 font-medium">Status</th>
                <th className="py-1 pr-3 font-medium">Grade</th>
                <th className="py-1 pr-3 font-medium">Output</th>
                <th className="py-1 font-medium" aria-label="Actions" />
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {tests.runs.map((run) => (
                <RunRow
                  key={run.id}
                  workspaceId={workspaceId}
                  run={run}
                  busy={busy}
                  onRerun={() =>
                    act(() => rerunSkillTest(workspaceId, itemId, run.id))
                  }
                  onGrade={() =>
                    act(() => gradeSkillTest(workspaceId, itemId, run.id))
                  }
                />
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function TemplateForm({
  workspaceId,
  itemId,
  tests,
}: {
  workspaceId: string;
  itemId: number;
  tests: SkillTests;
}) {
  const [template, setTemplate] = useState(tests.template);
  const [checklist, setChecklist] = useState(tests.checklist);
  const [status, setStatus] = useState<{
    error: string | null;
    saved?: boolean;
  }>({
    error: null,
  });
  const [busy, start] = useTransition();
  return (
    <section className="grid gap-3 md:grid-cols-2">
      <Field
        label="Run template"
        hint="The card's text. {skill} is the skill's name, {input} the test input. Empty: AGOS's default."
      >
        <Textarea
          rows={5}
          value={template}
          placeholder={tests.defaultTemplate}
          onChange={(e) => setTemplate(e.target.value)}
        />
      </Field>
      <Field
        label="Grading checklist"
        hint="What every passing output must satisfy, one line each. Empty: only an input's expected output grades it."
      >
        <Textarea
          rows={5}
          value={checklist}
          onChange={(e) => setChecklist(e.target.value)}
        />
      </Field>
      <div className="flex items-center gap-3 md:col-span-2">
        <Button
          disabled={
            busy ||
            (template === tests.template && checklist === tests.checklist)
          }
          onClick={() =>
            start(async () => {
              setStatus(
                await saveSkillTestSettings(
                  workspaceId,
                  itemId,
                  template,
                  checklist,
                ),
              );
            })
          }
        >
          Save
        </Button>
        <FormStatus error={status.error} saved={status.saved} />
      </div>
    </section>
  );
}

type InputDraft = { name: string; text: string; expected: string };

function InputRow({
  input,
  busy,
  onRun,
  onSave,
  onDelete,
}: {
  input: SkillTestInput;
  busy: boolean;
  onRun: () => void;
  onSave: (draft: InputDraft) => void;
  onDelete: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<InputDraft>(input);
  return (
    <div className="rounded-xl border border-line px-4 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-40 flex-1">
          <p className="text-sm font-medium">{input.name}</p>
          <p className="truncate text-xs text-ink-3">{input.text}</p>
        </div>
        <span className="text-xs text-ink-3">
          {input.expected ? "has an expected output" : "no expected output"}
        </span>
        <Button variant="primary" disabled={busy} onClick={onRun}>
          Run test
        </Button>
        <button
          type="button"
          className="text-sm text-ink-2 hover:text-ink"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? "Close" : "Edit"}
        </button>
        <button
          type="button"
          className="text-sm text-danger hover:underline"
          disabled={busy}
          onClick={onDelete}
        >
          Delete
        </button>
      </div>
      {open && (
        <InputFields
          draft={draft}
          setDraft={setDraft}
          busy={busy}
          label="Save"
          onSubmit={() => {
            onSave(draft);
            setOpen(false);
          }}
        />
      )}
    </div>
  );
}

function NewInput({
  busy,
  onAdd,
}: {
  busy: boolean;
  onAdd: (draft: InputDraft) => void;
}) {
  const empty: InputDraft = { name: "", text: "", expected: "" };
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<InputDraft>(empty);
  if (!open) {
    return (
      <Button className="self-start" onClick={() => setOpen(true)}>
        Add input
      </Button>
    );
  }
  return (
    <div className="rounded-xl border border-line px-4 py-3">
      <InputFields
        draft={draft}
        setDraft={setDraft}
        busy={busy}
        label="Add"
        onSubmit={() => {
          onAdd(draft);
          setDraft(empty);
          setOpen(false);
        }}
      />
    </div>
  );
}

function InputFields({
  draft,
  setDraft,
  busy,
  label,
  onSubmit,
}: {
  draft: InputDraft;
  setDraft: (d: InputDraft) => void;
  busy: boolean;
  label: string;
  onSubmit: () => void;
}) {
  return (
    <div className="mt-3 grid gap-3 md:grid-cols-2">
      <Field label="Name" className="md:col-span-2">
        <Input
          value={draft.name}
          onChange={(e) => setDraft({ ...draft, name: e.target.value })}
        />
      </Field>
      <Field label="Input text" hint="What the member gets with the skill.">
        <Textarea
          rows={4}
          value={draft.text}
          onChange={(e) => setDraft({ ...draft, text: e.target.value })}
        />
      </Field>
      <Field
        label="Expected output"
        hint="Optional. The grader compares the card's result with it (substance, not wording)."
      >
        <Textarea
          rows={4}
          value={draft.expected}
          onChange={(e) => setDraft({ ...draft, expected: e.target.value })}
        />
      </Field>
      <Button
        className="self-start"
        disabled={busy || !draft.name.trim() || !draft.text.trim()}
        onClick={onSubmit}
      >
        {label}
      </Button>
    </div>
  );
}

const STATUS: Record<string, string> = {
  running: "On the Kanban",
  blocked: "Waiting",
  done: "Finished",
  lost: "Card gone",
};

function RunRow({
  workspaceId,
  run,
  busy,
  onRerun,
  onGrade,
}: {
  workspaceId: string;
  run: SkillTestRun;
  busy: boolean;
  onRerun: () => void;
  onGrade: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <tr className="align-top">
      <td className="py-2 pr-3">
        {run.inputName}
        <span className="block text-xs text-ink-3">{when(run.createdAt)}</span>
      </td>
      <td className="py-2 pr-3 font-mono">v{run.version}</td>
      <td className="py-2 pr-3 font-mono text-xs">
        {run.card ? (
          <Link
            href={`/w/${encodeURIComponent(workspaceId)}/kanban?card=${encodeURIComponent(run.card)}`}
            className="text-accent hover:underline"
          >
            {run.card}
          </Link>
        ) : (
          "—"
        )}
      </td>
      <td className="py-2 pr-3">{STATUS[run.status] ?? run.status}</td>
      <td className="py-2 pr-3">
        {run.grade === "pass" ? (
          <span className="rounded-full bg-success-soft px-2 text-xs font-medium text-success">
            pass
          </span>
        ) : run.grade === "fail" ? (
          <span className="rounded-full bg-danger-soft px-2 text-xs font-medium text-danger">
            fail
          </span>
        ) : run.grade === "error" ? (
          <span className="text-xs text-ink-3" title={run.notes}>
            not graded
          </span>
        ) : run.status === "done" && run.gradable ? (
          <span className="text-xs text-ink-3">grading…</span>
        ) : (
          <span className="text-xs text-ink-3">—</span>
        )}
        {run.notes && run.grade !== "error" && (
          <span className="block max-w-60 text-xs text-ink-3">{run.notes}</span>
        )}
      </td>
      <td className="py-2 pr-3">
        {run.output ? (
          <>
            <button
              type="button"
              className="text-ink-2 hover:text-ink"
              onClick={() => setOpen((v) => !v)}
            >
              {open ? "Hide" : "Show"}
            </button>
            {open && (
              <pre className="mt-1 max-h-60 max-w-md overflow-auto rounded bg-sunken p-2 text-xs whitespace-pre-wrap">
                {run.output}
              </pre>
            )}
          </>
        ) : (
          <span className="text-xs text-ink-3">—</span>
        )}
      </td>
      <td className="py-2 text-right whitespace-nowrap">
        <div className="flex justify-end gap-3">
          <button
            type="button"
            className="text-ink-2 hover:text-ink"
            disabled={busy}
            onClick={onRerun}
          >
            Re-run
          </button>
          {run.status === "done" && run.gradable && (
            <button
              type="button"
              className="text-ink-2 hover:text-ink"
              disabled={busy}
              onClick={onGrade}
            >
              Grade again
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}
