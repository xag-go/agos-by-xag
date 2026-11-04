"use client";

import { useState, useTransition, type ReactNode } from "react";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { Input, Select } from "@/shared/ui/field";
import { deleteBoardView, saveBoardView } from "./board-actions";
import { labelClass, type BoardLabel } from "./labels";
import {
  COLUMNS,
  filtered,
  GROUPS,
  queryFrom,
  SORTS,
  type BoardQuery,
  type GoalNode,
  type SavedView,
} from "./views";

export type Member = { name: string; title: string };

const REVIEW_CHOICES: { value: BoardQuery["review"]; label: string }[] = [
  { value: "", label: "Any" },
  { value: "any", label: "Has review rules" },
  { value: "waiting", label: "In review now" },
  { value: "at_owner", label: "Waiting for your review" },
  { value: "stuck", label: "Stuck in review" },
  { value: "none", label: "No review rules" },
];
const BLOCKED_CHOICES: { value: BoardQuery["blocked"]; label: string }[] = [
  { value: "", label: "Any" },
  { value: "yes", label: "Blocked" },
  { value: "asks", label: "Needs your answer" },
  { value: "no", label: "Not blocked" },
];

function flip<T>(list: T[], value: T): T[] {
  return list.includes(value)
    ? list.filter((x) => x !== value)
    : [...list, value];
}

function chip(on: boolean) {
  return cn(
    "rounded-md border px-2 py-1 text-xs",
    on
      ? "border-ink bg-ink text-panel"
      : "border-line text-ink-2 hover:border-ink-3",
  );
}

export function Toolbar({
  workspaceId,
  q,
  views,
  labels,
  members,
  goals,
  columns,
  shown,
  total,
  go,
  selecting,
  onSelecting,
}: {
  workspaceId: string;
  q: BoardQuery;
  views: SavedView[];
  labels: BoardLabel[];
  members: Member[];
  goals: GoalNode[];
  columns: { status: string; label: string }[];
  shown: number;
  total: number;
  go: (q: BoardQuery) => void;
  selecting: boolean;
  onSelecting: (on: boolean) => void;
}) {
  const [busy, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [naming, setNaming] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const current = views.find((v) => v.id === q.view) ?? null;
  const set = (patch: Partial<BoardQuery>) => {
    go({ ...q, ...patch });
  };
  const save = (name: string, id: number | null) => {
    start(async () => {
      const r = await saveBoardView(workspaceId, name, q, id);
      setError(r.error);
      if (!r.error) {
        setNaming(null);
        if (r.id) go({ ...q, view: r.id });
      }
    });
  };
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Select
          aria-label="Saved view"
          className="w-44"
          value={q.view === null ? "" : String(q.view)}
          onChange={(e) => {
            go(
              queryFrom(e.target.value ? { view: e.target.value } : {}, views),
            );
          }}
        >
          <option value="">All cards</option>
          {views.map((v) => (
            <option key={v.id} value={String(v.id)}>
              {v.name}
            </option>
          ))}
        </Select>
        <Input
          key={`text-${q.text}`}
          aria-label="Find cards"
          placeholder="Find…"
          className="w-40"
          defaultValue={q.text}
          onKeyDown={(e) => {
            if (e.key === "Enter") set({ text: e.currentTarget.value });
          }}
          onBlur={(e) => {
            if (e.currentTarget.value !== q.text)
              set({ text: e.currentTarget.value });
          }}
        />
        <Button
          aria-expanded={open}
          onClick={() => {
            setOpen(!open);
          }}
        >
          Filters{filtered(q) ? " •" : ""}
        </Button>
        <label className="flex items-center gap-1.5 whitespace-nowrap text-sm text-ink-2">
          Group by
          <Select
            aria-label="Group by"
            className="w-32"
            value={q.groupBy}
            onChange={(e) => {
              set({ groupBy: e.target.value as BoardQuery["groupBy"] });
            }}
          >
            {GROUPS.map((g) => (
              <option key={g.value} value={g.value}>
                {g.label}
              </option>
            ))}
          </Select>
        </label>
        <Select
          aria-label="Sort"
          className="w-36"
          value={q.sort}
          onChange={(e) => {
            set({ sort: e.target.value as BoardQuery["sort"] });
          }}
        >
          {SORTS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </Select>
        <div
          className="flex rounded-lg border border-line-strong p-0.5"
          role="group"
          aria-label="Layout"
        >
          {(["board", "list"] as const).map((l) => (
            <button
              key={l}
              type="button"
              aria-pressed={q.layout === l}
              className={cn(
                "rounded-md px-2.5 py-1 text-sm",
                q.layout === l ? "bg-sunken text-ink" : "text-ink-3",
              )}
              onClick={() => {
                set({ layout: l });
              }}
            >
              {l === "board" ? "Kanban" : "List"}
            </button>
          ))}
        </div>
        <Button
          variant={selecting ? "primary" : "secondary"}
          aria-pressed={selecting}
          onClick={() => {
            onSelecting(!selecting);
          }}
        >
          {selecting ? "Done selecting" : "Select"}
        </Button>
        <span className="text-xs text-ink-3">
          {shown === total
            ? `${String(total)} cards`
            : `${String(shown)} of ${String(total)}`}
        </span>
        <span className="ml-auto flex items-center gap-2">
          {naming === null ? (
            <>
              {current && (
                <Button
                  variant="ghost"
                  disabled={busy}
                  onClick={() => {
                    save(current.name, current.id);
                  }}
                >
                  Update “{current.name}”
                </Button>
              )}
              <Button
                variant="ghost"
                onClick={() => {
                  setNaming("");
                }}
              >
                Save view…
              </Button>
              {current && (
                <Button
                  variant="ghost"
                  disabled={busy}
                  onClick={() => {
                    start(async () => {
                      const r = await deleteBoardView(workspaceId, current.id);
                      setError(r.error);
                      if (!r.error) go({ ...q, view: null });
                    });
                  }}
                >
                  Delete view
                </Button>
              )}
            </>
          ) : (
            <form
              className="flex items-center gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                save(naming, null);
              }}
            >
              <Input
                aria-label="View name"
                className="w-40"
                placeholder="View name"
                value={naming}
                onChange={(e) => {
                  setNaming(e.target.value);
                }}
              />
              <Button
                type="submit"
                variant="primary"
                disabled={busy || !naming.trim()}
              >
                Save
              </Button>
              <Button
                variant="ghost"
                onClick={() => {
                  setNaming(null);
                }}
              >
                Cancel
              </Button>
            </form>
          )}
        </span>
      </div>
      {error && <p className="text-sm text-danger">{error}</p>}
      {open && (
        <div className="flex flex-col gap-2 rounded-xl border border-line bg-panel p-3 text-sm">
          <Row label="Member">
            {[...members, { name: "", title: "Nobody yet" }].map((m) => (
              <button
                key={m.name || "nobody"}
                type="button"
                className={chip(q.members.includes(m.name))}
                onClick={() => {
                  set({ members: flip(q.members, m.name) });
                }}
              >
                {m.title}
              </button>
            ))}
          </Row>
          <Row label="Status">
            {columns.map((c) => (
              <button
                key={c.status}
                type="button"
                className={chip(q.statuses.includes(c.status))}
                onClick={() => {
                  set({ statuses: flip(q.statuses, c.status) });
                }}
              >
                {c.label}
              </button>
            ))}
          </Row>
          {labels.length > 0 && (
            <Row label="Label">
              {labels.map((l) => (
                <button
                  key={l.id}
                  type="button"
                  className={cn(
                    chip(q.labels.includes(l.id)),
                    !q.labels.includes(l.id) && labelClass(l.color),
                  )}
                  onClick={() => {
                    set({ labels: flip(q.labels, l.id) });
                  }}
                >
                  {l.folder ? `${l.folder} / ` : ""}
                  {l.name}
                </button>
              ))}
            </Row>
          )}
          <Row label="Goal / project">
            <Select
              aria-label="Goal or project"
              className="w-64"
              value={q.goal === null ? "" : String(q.goal)}
              onChange={(e) => {
                set({ goal: e.target.value ? Number(e.target.value) : null });
              }}
            >
              <option value="">Any</option>
              {goals.map((g) => (
                <option key={g.id} value={String(g.id)}>
                  {g.level === "project" ? "↳ " : ""}
                  {g.title}
                </option>
              ))}
            </Select>
          </Row>
          <Row label="Review">
            <Select
              aria-label="Review state"
              className="w-56"
              value={q.review}
              onChange={(e) => {
                set({ review: e.target.value as BoardQuery["review"] });
              }}
            >
              {REVIEW_CHOICES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </Select>
          </Row>
          <Row label="Blocked">
            <Select
              aria-label="Blocked"
              className="w-56"
              value={q.blocked}
              onChange={(e) => {
                set({ blocked: e.target.value as BoardQuery["blocked"] });
              }}
            >
              {BLOCKED_CHOICES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </Select>
          </Row>
          {q.layout === "list" && (
            <Row label="Columns">
              {COLUMNS.map((c) => (
                <button
                  key={c.value}
                  type="button"
                  className={chip(q.columns.includes(c.value))}
                  onClick={() => {
                    const next = flip(q.columns, c.value);
                    set({
                      columns: COLUMNS.map((x) => x.value).filter((v) =>
                        next.includes(v),
                      ),
                    });
                  }}
                >
                  {c.label}
                </button>
              ))}
            </Row>
          )}
          {filtered(q) && (
            <div>
              <Button
                variant="ghost"
                onClick={() => {
                  set({
                    members: [],
                    statuses: [],
                    labels: [],
                    goal: null,
                    review: "",
                    blocked: "",
                    text: "",
                  });
                }}
              >
                Clear filters
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="w-28 shrink-0 text-xs font-medium tracking-wide text-ink-3 uppercase">
        {label}
      </span>
      {children}
    </div>
  );
}
