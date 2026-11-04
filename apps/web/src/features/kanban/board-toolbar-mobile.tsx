"use client";

/** The board toolbar's phone layout (below md): two compact rows on the board and
 * the extra controls at the top of the Filters sheet. Desktop never renders these. */

import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { Input, Select } from "@/shared/ui/field";
import {
  GROUPS,
  queryFrom,
  SORTS,
  type BoardQuery,
  type SavedView,
} from "./views";

export type MobileToolbar = {
  q: BoardQuery;
  views: SavedView[];
  set: (patch: Partial<BoardQuery>) => void;
  go: (q: BoardQuery) => void;
  open: boolean;
  setOpen: (open: boolean) => void;
  shown: number;
  total: number;
  selecting: boolean;
  onSelecting: (on: boolean) => void;
  naming: string | null;
  setNaming: (name: string | null) => void;
  current: SavedView | null;
  busy: boolean;
  save: (name: string, id: number | null) => void;
  remove: (view: SavedView) => void;
};

/** How many filter dimensions are on (the phone's Filters badge). */
export function activeFilters(q: BoardQuery): number {
  return (
    q.members.length +
    q.statuses.length +
    q.labels.length +
    (q.goal !== null ? 1 : 0) +
    (q.review !== "" ? 1 : 0) +
    (q.blocked !== "" ? 1 : 0)
  );
}

/** Small screens: search + Filters, then layout + count. */
export function MobileToolbarRows({
  q,
  set,
  open,
  setOpen,
  shown,
  total,
}: MobileToolbar) {
  const active = activeFilters(q);
  return (
    <div className="flex flex-col gap-2 md:hidden">
      <div className="flex items-center gap-2">
        <Input
          key={`m-text-${q.text}`}
          aria-label="Find cards"
          placeholder="Find…"
          className="max-md:h-11 min-w-0 flex-1"
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
          className="!h-11 shrink-0"
          aria-expanded={open}
          onClick={() => {
            setOpen(!open);
          }}
        >
          Filters
          {active > 0 && (
            <span className="rounded-full bg-ink px-1.5 text-xs font-medium text-panel">
              {active}
            </span>
          )}
        </Button>
      </div>
      <div className="flex items-center gap-2">
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
                "h-11 rounded-md px-4 text-sm",
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
        <span className="ml-auto text-xs text-ink-3">
          {shown === total
            ? `${String(total)} cards`
            : `${String(shown)} of ${String(total)}`}
        </span>
      </div>
    </div>
  );
}

/** The Filters sheet's phone-only pickers: saved view, group, sort. */
function MobilePickers({ q, views, set, go }: MobileToolbar) {
  return (
    <>
      <label className="flex flex-col gap-1.5">
        <span className="text-xs font-medium tracking-wide text-ink-3 uppercase">
          View
        </span>
        <Select
          aria-label="Saved view"
          className="max-md:h-11 w-full"
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
      </label>
      <div className="grid grid-cols-2 gap-2">
        <label className="flex min-w-0 flex-col gap-1.5">
          <span className="text-xs font-medium tracking-wide text-ink-3 uppercase">
            Group by
          </span>
          <Select
            aria-label="Group by"
            className="max-md:h-11 w-full"
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
        <label className="flex min-w-0 flex-col gap-1.5">
          <span className="text-xs font-medium tracking-wide text-ink-3 uppercase">
            Sort
          </span>
          <Select
            aria-label="Sort"
            className="max-md:h-11 w-full"
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
        </label>
      </div>
    </>
  );
}

/** Select, save/update/delete the saved view. */
function MobileViewButtons({
  selecting,
  onSelecting,
  setNaming,
  current,
  busy,
  save,
  remove,
}: MobileToolbar) {
  return (
    <div className="flex flex-wrap gap-2">
      <Button
        className="!h-11 flex-1"
        variant={selecting ? "primary" : "secondary"}
        aria-pressed={selecting}
        onClick={() => {
          onSelecting(!selecting);
        }}
      >
        {selecting ? "Done selecting" : "Select"}
      </Button>
      <Button
        className="!h-11 flex-1"
        variant="ghost"
        onClick={() => {
          setNaming("");
        }}
      >
        Save view…
      </Button>
      {current && (
        <Button
          className="!h-11 flex-1"
          variant="ghost"
          disabled={busy}
          onClick={() => {
            save(current.name, current.id);
          }}
        >
          Update “{current.name}”
        </Button>
      )}
      {current && (
        <Button
          className="!h-11 flex-1"
          variant="ghost"
          disabled={busy}
          onClick={() => {
            remove(current);
          }}
        >
          Delete view
        </Button>
      )}
    </div>
  );
}

function MobileNameForm({ naming, setNaming, busy, save }: MobileToolbar) {
  if (naming === null) return null;
  return (
    <form
      className="flex items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        save(naming, null);
      }}
    >
      <Input
        aria-label="View name"
        className="max-md:h-11 min-w-0 flex-1"
        placeholder="View name"
        value={naming}
        onChange={(e) => {
          setNaming(e.target.value);
        }}
      />
      <Button
        type="submit"
        className="!h-11"
        variant="primary"
        disabled={busy || !naming.trim()}
      >
        Save
      </Button>
      <Button
        className="!h-11"
        variant="ghost"
        onClick={() => {
          setNaming(null);
        }}
      >
        Cancel
      </Button>
    </form>
  );
}

/** Small screens only: the controls the compact toolbar tucked into the sheet. */
export function MobileSheetControls(t: MobileToolbar) {
  return (
    <div className="flex flex-col gap-3 border-b border-line pb-3 md:hidden">
      <MobilePickers {...t} />
      {t.naming === null ? (
        <MobileViewButtons {...t} />
      ) : (
        <MobileNameForm {...t} />
      )}
    </div>
  );
}
