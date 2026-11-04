"use client";

import { useState } from "react";
import type { PlanNode } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { useAsk } from "@/shared/ui/confirm";
import { Input, Select } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { PlusIcon, TrashIcon } from "@/shared/ui/icons";
import {
  changeItem,
  changeResult,
  deleteItem,
  deleteResult,
  type ItemChanges,
} from "./actions";
import { useRun } from "./use-run";
import { escapeTo } from "./goal-keys";
import { type Kind, type Member, type Status } from "./goal-model";
import { sectionLabel, small } from "./goal-styles";
import {
  projectChanges,
  projectDraft,
  resultChanges,
  resultDraft,
  type ProjectDraft,
  type ResultDraft,
} from "./goal-drafts";
import { OwnerSelect, StatusSelect } from "./goal-chips";

/** One goal's whole edit form: its own fields, its key results (numbers
 * included) and its projects. Removals wait for Save (Undo until then). */
export function GoalEditor({
  workspaceId,
  goal,
  members,
  onDone,
}: {
  workspaceId: string;
  goal: PlanNode;
  members: Member[];
  onDone: () => void;
}) {
  const [busy, error, run] = useRun();
  const { dialog, confirm } = useAsk();
  const [title, setTitle] = useState(goal.title);
  const [owner, setOwner] = useState(goal.owner);
  const [dueOn, setDueOn] = useState(goal.dueOn);
  const [status, setStatus] = useState<Status>(goal.status);
  const [results, setResults] = useState(() =>
    (goal.results ?? []).map(resultDraft),
  );
  const [projects, setProjects] = useState(() =>
    (goal.children ?? []).map(projectDraft),
  );
  const editResult = (id: number, patch: Partial<ResultDraft>) => {
    setResults((rs) => rs.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  };
  const editProject = (id: number, patch: Partial<ProjectDraft>) => {
    setProjects((ps) => ps.map((p) => (p.id === id ? { ...p, ...patch } : p)));
  };

  const save = () => {
    run(async () => {
      const name = title.trim();
      if (!name) return { error: "Give the goal a title." };
      const goalChanges: ItemChanges = {};
      if (name !== goal.title) goalChanges.title = name;
      if (owner !== goal.owner) goalChanges.owner = owner;
      if (dueOn !== goal.dueOn) goalChanges.dueOn = dueOn;
      if (status !== goal.status) goalChanges.status = status;
      // Check every row first, so a typo saves nothing.
      const resultJobs: (() => Promise<{ error: string | null }>)[] = [];
      for (const d of results) {
        const k = goal.results?.find((r) => r.id === d.id);
        if (!k) continue;
        if (d.gone) {
          resultJobs.push(() => deleteResult(workspaceId, d.id));
          continue;
        }
        const changes = resultChanges(k, d);
        if (typeof changes === "string") return { error: changes };
        if (changes)
          resultJobs.push(() => changeResult(workspaceId, d.id, changes));
      }
      const projectJobs: (() => Promise<{ error: string | null }>)[] = [];
      for (const d of projects) {
        const p = goal.children?.find((c) => c.id === d.id);
        if (!p) continue;
        if (d.gone) {
          projectJobs.push(() => deleteItem(workspaceId, d.id));
          continue;
        }
        const changes = projectChanges(p, d);
        if (typeof changes === "string") return { error: changes };
        if (changes)
          projectJobs.push(() => changeItem(workspaceId, d.id, changes));
      }
      const jobs = [
        ...(Object.keys(goalChanges).length > 0
          ? [() => changeItem(workspaceId, goal.id, goalChanges)]
          : []),
        ...resultJobs,
        ...projectJobs,
      ];
      for (const job of jobs) {
        const r = await job();
        if (r.error) return r;
      }
      onDone();
      return { error: null };
    });
  };

  return (
    <>
      {/* Outside the form: the popup has its own form, whose submit would
          bubble into this one's. */}
      {dialog}
      <form
        className="flex flex-col gap-4"
        aria-label={`Edit goal ${goal.title}`}
        onSubmit={(e) => {
          e.preventDefault();
          save();
        }}
        onKeyDown={escapeTo(onDone)}
      >
        <div className="flex flex-col gap-2">
          <p className={sectionLabel}>Goal #{goal.id}</p>
          <Input
            aria-label="Goal title"
            value={title}
            maxLength={200}
            autoFocus
            disabled={busy}
            onChange={(e) => {
              setTitle(e.target.value);
            }}
          />
          <div className="flex flex-wrap items-center gap-2">
            <OwnerSelect
              value={owner}
              members={members}
              disabled={busy}
              onChange={setOwner}
            />
            <Input
              type="date"
              aria-label="Due"
              className={cn(small, "!w-auto")}
              value={dueOn}
              disabled={busy}
              onChange={(e) => {
                setDueOn(e.target.value);
              }}
            />
            <StatusSelect value={status} disabled={busy} onChange={setStatus} />
          </div>
        </div>

        {results.length > 0 && (
          <div className="flex flex-col gap-2">
            <p className={sectionLabel}>Key results</p>
            {results.map((d) =>
              d.gone ? (
                <Removed
                  key={d.id}
                  what={d.title}
                  onUndo={() => {
                    editResult(d.id, { gone: false });
                  }}
                />
              ) : (
                <div
                  key={d.id}
                  className="flex flex-wrap items-center gap-1.5 rounded-lg bg-sunken/60 px-2.5 py-2"
                >
                  <Input
                    aria-label="Key result title"
                    className={cn(small, "!w-auto min-w-40 flex-1")}
                    value={d.title}
                    maxLength={200}
                    disabled={busy}
                    onChange={(e) => {
                      editResult(d.id, { title: e.target.value });
                    }}
                  />
                  <Input
                    aria-label={`${d.title}: current value`}
                    inputMode="decimal"
                    className={cn(small, "!w-20 text-right tabular-nums")}
                    value={d.current}
                    disabled={busy}
                    onChange={(e) => {
                      editResult(d.id, { current: e.target.value });
                    }}
                  />
                  <span className="text-xs text-ink-3">/</span>
                  <Input
                    aria-label={`${d.title}: target`}
                    inputMode="decimal"
                    placeholder="Target"
                    className={cn(small, "!w-20 text-right tabular-nums")}
                    value={d.target}
                    disabled={busy}
                    onChange={(e) => {
                      editResult(d.id, { target: e.target.value });
                    }}
                  />
                  <Input
                    aria-label={`${d.title}: unit`}
                    placeholder="Unit"
                    className={cn(small, "!w-24")}
                    value={d.unit}
                    maxLength={40}
                    disabled={busy}
                    onChange={(e) => {
                      editResult(d.id, { unit: e.target.value });
                    }}
                  />
                  <Input
                    type="date"
                    aria-label={`${d.title}: due`}
                    className={cn(small, "!w-auto")}
                    value={d.dueOn}
                    disabled={busy}
                    onChange={(e) => {
                      editResult(d.id, { dueOn: e.target.value });
                    }}
                  />
                  <Button
                    variant="ghost"
                    className="h-8 px-1.5 text-xs"
                    aria-label={`Remove key result ${d.title}`}
                    disabled={busy}
                    onClick={() => {
                      editResult(d.id, { gone: true });
                    }}
                  >
                    <TrashIcon />
                  </Button>
                </div>
              ),
            )}
          </div>
        )}

        {projects.length > 0 && (
          <div className="flex flex-col gap-2">
            <p className={sectionLabel}>Projects</p>
            {projects.map((d) =>
              d.gone ? (
                <Removed
                  key={d.id}
                  what={d.title}
                  onUndo={() => {
                    editProject(d.id, { gone: false });
                  }}
                />
              ) : (
                <div
                  key={d.id}
                  className="flex flex-wrap items-center gap-1.5 rounded-lg bg-sunken/60 px-2.5 py-2"
                >
                  <Input
                    aria-label="Project title"
                    className={cn(small, "!w-auto min-w-40 flex-1")}
                    value={d.title}
                    maxLength={200}
                    disabled={busy}
                    onChange={(e) => {
                      editProject(d.id, { title: e.target.value });
                    }}
                  />
                  <OwnerSelect
                    value={d.owner}
                    members={members}
                    disabled={busy}
                    onChange={(o) => {
                      editProject(d.id, { owner: o });
                    }}
                  />
                  <StatusSelect
                    value={d.status}
                    disabled={busy}
                    onChange={(s) => {
                      editProject(d.id, { status: s });
                    }}
                  />
                  <KindFields
                    kind={d.projectKind}
                    startsOn={d.startsOn}
                    endsOn={d.endsOn}
                    rhythm={d.rhythm}
                    disabled={busy}
                    onChange={(patch) => {
                      editProject(d.id, patch);
                    }}
                  />
                  <Button
                    variant="ghost"
                    className="h-8 px-1.5 text-xs"
                    aria-label={`Remove project ${d.title}`}
                    disabled={busy}
                    onClick={() => {
                      editProject(d.id, { gone: true });
                    }}
                  >
                    <TrashIcon />
                  </Button>
                </div>
              ),
            )}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3">
          <Button type="submit" variant="primary" disabled={busy}>
            {busy ? "Saving…" : "Save"}
          </Button>
          <Button variant="ghost" disabled={busy} onClick={onDone}>
            Cancel
          </Button>
          <FormStatus error={error} />
          <Button
            variant="danger"
            className="ml-auto"
            disabled={busy}
            onClick={() => {
              void confirm({
                title: `Delete “${goal.title}”?`,
                body: "Its projects and key results go too. Cards that named it keep their line.",
                confirmLabel: "Delete",
                danger: true,
              }).then((ok) => {
                if (ok) run(() => deleteItem(workspaceId, goal.id));
              });
            }}
          >
            <TrashIcon /> Delete goal
          </Button>
        </div>
      </form>
    </>
  );
}

function Removed({ what, onUndo }: { what: string; onUndo: () => void }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-dashed border-line px-2.5 py-1.5 text-sm text-ink-3">
      <span className="min-w-0 flex-1 truncate">
        “{what}” is removed when you save.
      </span>
      <Button variant="ghost" className="h-7 px-2 text-xs" onClick={onUndo}>
        Undo
      </Button>
    </div>
  );
}

export function KindFields({
  kind,
  startsOn,
  endsOn,
  rhythm,
  disabled,
  onChange,
}: {
  kind: Kind;
  startsOn: string;
  endsOn: string;
  rhythm: string;
  disabled?: boolean;
  onChange: (
    patch: Partial<{
      projectKind: Kind;
      startsOn: string;
      endsOn: string;
      rhythm: string;
    }>,
  ) => void;
}) {
  return (
    <>
      <Select
        aria-label="Kind"
        className={cn(small, "!w-auto")}
        value={kind}
        disabled={disabled}
        onChange={(e) => {
          onChange({ projectKind: e.target.value as Kind });
        }}
      >
        <option value="dated">Dated</option>
        <option value="recurring">Recurring</option>
      </Select>
      {kind === "dated" ? (
        <>
          <Input
            type="date"
            aria-label="Start"
            className={cn(small, "!w-auto")}
            value={startsOn}
            disabled={disabled}
            onChange={(e) => {
              onChange({ startsOn: e.target.value });
            }}
          />
          <Input
            type="date"
            aria-label="End"
            className={cn(small, "!w-auto")}
            value={endsOn}
            disabled={disabled}
            onChange={(e) => {
              onChange({ endsOn: e.target.value });
            }}
          />
        </>
      ) : (
        <Input
          aria-label="Rhythm"
          className={cn(small, "!w-40")}
          value={rhythm}
          maxLength={120}
          placeholder="4 reels a week"
          disabled={disabled}
          onChange={(e) => {
            onChange({ rhythm: e.target.value });
          }}
        />
      )}
    </>
  );
}

export function FormActions({
  busy,
  canAdd,
  error,
  onClose,
}: {
  busy: boolean;
  canAdd: boolean;
  error: string | null;
  onClose: () => void;
}) {
  return (
    <div className="flex w-full flex-wrap items-center gap-2">
      <Button
        type="submit"
        variant="primary"
        className="h-8 px-3 text-xs"
        disabled={busy || !canAdd}
      >
        <PlusIcon /> Add
      </Button>
      <Button
        variant="ghost"
        className="h-8 px-3 text-xs"
        disabled={busy}
        onClick={onClose}
      >
        Cancel
      </Button>
      <FormStatus error={error} />
    </div>
  );
}
