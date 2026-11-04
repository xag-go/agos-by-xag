"use client";

import { useState } from "react";
import { cn } from "@/shared/ui/cn";
import type { FoundProject, FoundResult, GoalPayload } from "../proposal-types";
import { DailyPlan } from "./daily-plan";
import { Row } from "./row";

const CHANGE_WORDS: Record<string, string> = {
  suggest_vision: "Suggest a new Vision",
  add_goal: "Add a goal",
  update_goal: "Change a goal",
  drop_goal: "Drop a goal",
  add_kr: "Add a key result",
  update_kr: "Change a key result",
  drop_kr: "Drop a key result",
  kr_update: "New number for a key result",
  add_project: "Add a project",
  update_project: "Change a project",
  drop_project: "Drop a project",
  delete_goal: "Delete a goal, with its key results and projects",
  delete_kr: "Delete a key result",
  delete_project: "Delete a project",
  daily_plan: "Today's plan",
  set_goal: "Set the workspace goal",
  add_subgoal: "Add a sub-goal",
  update_subgoal: "Change a sub-goal",
  drop_subgoal: "Drop a sub-goal",
};

type EditField = {
  key: string;
  label: string;
  type?: "number" | "date" | "kind";
};

const GOAL_FIELDS: EditField[] = [
  { key: "title", label: "Title" },
  { key: "goal_why", label: "Why" },
  { key: "owner", label: "Owner" },
  { key: "due_on", label: "Due", type: "date" },
];
const KR_FIELDS: EditField[] = [
  { key: "title", label: "Measures" },
  { key: "start", label: "Start", type: "number" },
  { key: "current", label: "Current", type: "number" },
  { key: "target", label: "Target", type: "number" },
  { key: "unit", label: "Unit" },
  { key: "due_on", label: "Due", type: "date" },
];
const PROJECT_FIELDS: EditField[] = [
  { key: "title", label: "Title" },
  { key: "owner", label: "Owner" },
  { key: "project_kind", label: "Kind", type: "kind" },
  { key: "starts_on", label: "Starts", type: "date" },
  { key: "ends_on", label: "Ends", type: "date" },
  { key: "rhythm", label: "Rhythm" },
];

/** What the owner may edit before approving, per change. */
const EDITABLE: Record<string, EditField[]> = {
  suggest_vision: [
    { key: "title", label: "Vision" },
    { key: "vision_why", label: "Why" },
    { key: "strategy", label: "Strategy" },
  ],
  add_goal: GOAL_FIELDS,
  update_goal: GOAL_FIELDS,
  add_kr: KR_FIELDS,
  update_kr: KR_FIELDS,
  kr_update: [
    { key: "current", label: "New number", type: "number" },
    { key: "source", label: "Source" },
  ],
  add_project: PROJECT_FIELDS,
  update_project: PROJECT_FIELDS,
};

function shown(value: unknown): string {
  if (typeof value === "string") return value;
  return typeof value === "number" ? String(value) : "";
}

export function GoalDetails({
  payload: g,
  edits,
  onEdit,
}: {
  payload: GoalPayload;
  edits: Record<string, unknown>;
  /** Editable (the Inbox): the owner's edits go with the approve. */
  onEdit?: (edits: Record<string, unknown>) => void;
}) {
  const [editing, setEditing] = useState(false);
  const fields = EDITABLE[g.change ?? ""] ?? [];
  const value = (key: string) => (key in edits ? edits[key] : g[key]);
  const ids = [
    g.goal_id ? `goal #${String(g.goal_id)}` : "",
    g.kr_id ? `key result #${String(g.kr_id)}` : "",
    g.project_id ? `project #${String(g.project_id)}` : "",
  ].filter(Boolean);
  if (g.change === "daily_plan")
    return <DailyPlan payload={g} edits={edits} onEdit={onEdit} />;
  return (
    <div className="flex flex-col gap-1">
      <Row label="Change">
        {CHANGE_WORDS[g.change ?? ""] ?? g.change}
        {ids.length > 0 ? ` (${ids.join(", ")})` : ""}
      </Row>
      {editing && onEdit ? (
        <div className="flex flex-col gap-1.5 rounded-lg bg-sunken/60 px-2.5 py-2">
          {fields.map((f) => (
            <label key={f.key} className="flex items-center gap-2 text-sm">
              <span className="w-24 shrink-0 text-ink-3">{f.label}</span>
              {f.type === "kind" ? (
                <select
                  className="h-8 rounded-md border border-line bg-panel px-2 text-sm"
                  value={shown(value(f.key)) || "dated"}
                  onChange={(e) => {
                    onEdit({ ...edits, [f.key]: e.target.value });
                  }}
                >
                  <option value="dated">Dated</option>
                  <option value="recurring">Recurring</option>
                </select>
              ) : (
                <input
                  className="h-8 min-w-0 flex-1 rounded-md border border-line bg-panel px-2 text-sm"
                  type={f.type === "date" ? "date" : "text"}
                  inputMode={f.type === "number" ? "decimal" : undefined}
                  aria-label={f.label}
                  value={shown(value(f.key))}
                  onChange={(e) => {
                    const raw = e.target.value;
                    const next =
                      f.type === "number" &&
                      raw.trim() !== "" &&
                      Number.isFinite(Number(raw))
                        ? Number(raw)
                        : raw;
                    onEdit({ ...edits, [f.key]: next });
                  }}
                />
              )}
            </label>
          ))}
        </div>
      ) : (
        fields
          .filter((f) => shown(value(f.key)) !== "")
          .map((f) => (
            <Row key={f.key} label={f.label}>
              <span className={cn(f.key in edits && "font-medium text-accent")}>
                {f.key === "owner"
                  ? `@${shown(value(f.key))}`
                  : shown(value(f.key))}
              </span>
            </Row>
          ))
      )}
      {fields.length === 0 && g.title && (
        <Row label="Title">
          <span className="font-medium">{g.title}</span>
        </Row>
      )}
      {fields.length === 0 && g.owner && <Row label="Owner">@{g.owner}</Row>}
      {g.status && <Row label="Status">{g.status}</Row>}
      {g.measure && <Row label="Reached when">{g.measure}</Row>}
      {g.why && (
        <Row label="Why">
          <span className="whitespace-pre-wrap">{g.why}</span>
        </Row>
      )}
      {g.change === "add_goal" && (
        <GoalParts
          payload={g}
          edits={edits}
          onEdit={editing ? onEdit : undefined}
        />
      )}
      {onEdit && fields.length > 0 && (
        <button
          type="button"
          className="self-start text-xs text-ink-2 underline"
          onClick={() => {
            setEditing(!editing);
          }}
        >
          {editing ? "Done editing" : "Edit before approving"}
        </button>
      )}
    </div>
  );
}

/** A new goal's key results and projects (the Vision notes' Organize): the
 * owner rewords, renumbers or drops any before he approves. */
function GoalParts({
  payload: g,
  edits,
  onEdit,
}: {
  payload: GoalPayload;
  edits: Record<string, unknown>;
  onEdit?: (edits: Record<string, unknown>) => void;
}) {
  const results =
    (edits.key_results as FoundResult[] | undefined) ?? g.key_results ?? [];
  const projects =
    (edits.projects as FoundProject[] | undefined) ?? g.projects ?? [];
  if (results.length === 0 && projects.length === 0) return null;
  const input =
    "h-7 min-w-0 rounded-md border border-line bg-panel px-2 text-sm";
  const setResult = (n: number, change: Partial<FoundResult>) => {
    onEdit?.({
      ...edits,
      key_results: results.map((r, i) => (i === n ? { ...r, ...change } : r)),
    });
  };
  const drop =
    <T,>(key: "key_results" | "projects", items: T[], n: number) =>
    () => {
      onEdit?.({ ...edits, [key]: items.filter((_x, i) => i !== n) });
    };
  return (
    <div className="flex flex-col gap-1">
      {results.length > 0 && (
        <Row label="Key results">
          <ul className="flex flex-col gap-1">
            {results.map((r, n) =>
              onEdit ? (
                <li
                  key={`kr-${String(n)}`}
                  className="flex items-center gap-1.5"
                >
                  <input
                    className={cn(input, "flex-1")}
                    aria-label="Measures"
                    value={r.title}
                    onChange={(e) => {
                      setResult(n, { title: e.target.value });
                    }}
                  />
                  <input
                    className={cn(input, "w-20")}
                    aria-label="Target"
                    inputMode="decimal"
                    value={
                      r.target === null || r.target === undefined
                        ? ""
                        : String(r.target)
                    }
                    onChange={(e) => {
                      const raw = e.target.value.trim();
                      setResult(n, {
                        target:
                          raw !== "" && Number.isFinite(Number(raw))
                            ? Number(raw)
                            : null,
                      });
                    }}
                  />
                  <input
                    className={cn(input, "w-24")}
                    aria-label="Unit"
                    value={r.unit ?? ""}
                    onChange={(e) => {
                      setResult(n, { unit: e.target.value });
                    }}
                  />
                  <input
                    className={cn(input, "w-36")}
                    type="date"
                    aria-label="Due"
                    value={r.due_on ?? ""}
                    onChange={(e) => {
                      setResult(n, { due_on: e.target.value });
                    }}
                  />
                  <button
                    type="button"
                    className="text-xs text-ink-3 hover:text-danger"
                    aria-label={`Drop ${r.title}`}
                    onClick={drop("key_results", results, n)}
                  >
                    ✕
                  </button>
                </li>
              ) : (
                <li key={`kr-${String(n)}`}>
                  {r.title}
                  {r.target !== null && r.target !== undefined
                    ? `: ${String(r.target)}${r.unit ? ` ${r.unit}` : ""}`
                    : ""}
                  {r.due_on ? ` by ${r.due_on}` : ""}
                </li>
              ),
            )}
          </ul>
        </Row>
      )}
      {projects.length > 0 && (
        <Row label="Projects">
          <ul className="flex flex-col gap-1">
            {projects.map((p, n) =>
              onEdit ? (
                <li
                  key={`p-${String(n)}`}
                  className="flex items-center gap-1.5"
                >
                  <input
                    className={cn(input, "flex-1")}
                    aria-label="Project"
                    value={p.title}
                    onChange={(e) => {
                      onEdit({
                        ...edits,
                        projects: projects.map((x, i) =>
                          i === n ? { title: e.target.value } : x,
                        ),
                      });
                    }}
                  />
                  <button
                    type="button"
                    className="text-xs text-ink-3 hover:text-danger"
                    aria-label={`Drop ${p.title}`}
                    onClick={drop("projects", projects, n)}
                  >
                    ✕
                  </button>
                </li>
              ) : (
                <li key={`p-${String(n)}`}>{p.title}</li>
              ),
            )}
          </ul>
        </Row>
      )}
    </div>
  );
}
