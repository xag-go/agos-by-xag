"use client";

import {
  createContext,
  useMemo,
  useOptimistic,
  useState,
  useSyncExternalStore,
  useTransition,
  type CSSProperties,
  type DragEvent,
  type ReactNode,
} from "react";
import type { FolderKind, ListFolder } from "@/data/types";
import { cn } from "@/shared/ui/cn";
import { PANEL } from "@/shared/ui/panel";
import { useAsk } from "@/shared/ui/confirm";
import { Input } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { PlusIcon } from "@/shared/ui/icons";
import {
  createFolder,
  deleteFolder,
  moveToFolder,
  renameFolder,
} from "./actions";
import { plural } from "@/shared/format";

/** One row of a list: its id, the words a search matches, and what it shows. */
export type FolderEntry = {
  id: number;
  text: string;
  node: ReactNode;
  /** The row's own anchor id (e.g. `goal-12`), kept on its <li>. */
  rowId?: string;
};

type Move = { item: number; folder: number | null };

type Shared = {
  folders: ListFolder[];
  folderOf: (item: number) => number | null;
  move: (item: number, folder: number | null) => void;
  makeAndMove: (item: number) => void;
};

export const FolderContext = createContext<Shared | null>(null);

// Which folders are folded: this browser remembers it per workspace and list.
const FOLDED = "agos.folders.folded";
const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

function foldedKey(workspaceId: string, kind: FolderKind) {
  return `${FOLDED}.${workspaceId}.${kind}`;
}

function useFolded(workspaceId: string, kind: FolderKind) {
  const key = foldedKey(workspaceId, kind);
  const raw = useSyncExternalStore(
    subscribe,
    () => window.localStorage.getItem(key) ?? "[]",
    () => "[]",
  );
  const folded = useMemo(() => {
    try {
      const ids: unknown = JSON.parse(raw);
      return new Set(Array.isArray(ids) ? ids.map(Number) : []);
    } catch {
      return new Set<number>();
    }
  }, [raw]);
  const toggle = (id: number) => {
    const next = new Set(folded);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    window.localStorage.setItem(key, JSON.stringify([...next]));
    for (const l of listeners) l();
  };
  return { folded, toggle };
}

function moved(folders: ListFolder[], { item, folder }: Move): ListFolder[] {
  return folders.map((f) => ({
    ...f,
    items:
      f.id === folder
        ? [...(f.items ?? []).filter((i) => i !== item), item]
        : (f.items ?? []).filter((i) => i !== item),
  }));
}

const DRAG = "application/x-agos-folder-item";

/** “an automation”, “a skill”. */
const an = (word: string) => `${/^[aeiou]/i.test(word) ? "an" : "a"} ${word}`;

/**
 * A list grouped by the owner's folders (one level): each folder folds open or
 * shut (remembered), shows how many it holds, and is renamed or deleted from its
 * header (its items go back to "No folder"). Items move with their row's “Move”
 * menu or by dragging them onto a folder. A search finds items inside folders too.
 * Folders are AGOS's own: nothing of Hermes changes.
 */
export function FolderList({
  workspaceId,
  kind,
  noun,
  folders,
  entries,
  variant = "rows",
  rowClassName,
  after,
  gridStyle,
  empty,
  hideEmpty = false,
  toolbar = true,
}: {
  workspaceId: string;
  kind: FolderKind;
  /** What one item is called: "automation", "skill", "project". */
  noun: string;
  folders: ListFolder[];
  entries: FolderEntry[];
  /** rows = one bordered list (Automations, Skills); cards = a grid (Projects). */
  variant?: "rows" | "cards";
  rowClassName: string;
  /** Last in the "No folder" list (e.g. the “+ New project” tile). */
  after?: ReactNode;
  /** The cards grid's own style for n cards. */
  gridStyle?: (n: number) => CSSProperties;
  /** Shown instead when there is nothing at all. */
  empty?: ReactNode;
  /** One part of a bigger list (a goal's projects): a folder whose items are all
   * elsewhere is left out here; an empty one shows. */
  hideEmpty?: boolean;
  /** The Find box and “New folder” above the list (off: the page puts a
   * NewFolderButton in its own header). */
  toolbar?: boolean;
}) {
  const [shown, setShown] = useOptimistic(folders, moved);
  const [, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [over, setOver] = useState<number | "none" | null>(null);
  const { folded, toggle } = useFolded(workspaceId, kind);
  const { dialog, ask, confirm } = useAsk();

  const ids = new Set(entries.map((e) => e.id));
  const folderOf = (item: number) =>
    shown.find((f) => (f.items ?? []).includes(item))?.id ?? null;
  const move = (item: number, folder: number | null) => {
    if (folderOf(item) === folder) return;
    setError(null);
    start(async () => {
      setShown({ item, folder });
      const r = await moveToFolder(workspaceId, kind, item, folder);
      if (r.error) setError(r.error);
    });
  };
  const newFolder = async (then?: number) => {
    const name = await ask({
      title: "New folder",
      body: `A folder groups ${noun}s on this page only: it changes nothing in how they run.`,
      input: { label: "Name", initial: "" },
      confirmLabel: "Create folder",
    });
    if (!name?.trim()) return;
    setError(null);
    start(async () => {
      const r = await createFolder(workspaceId, kind, name);
      if (r.error) {
        setError(r.error);
        return;
      }
      if (then === undefined || r.id === undefined) return;
      const m = await moveToFolder(workspaceId, kind, then, r.id);
      if (m.error) setError(m.error);
    });
  };
  const rename = async (f: ListFolder) => {
    const name = await ask({
      title: `Rename “${f.name}”`,
      input: { label: "Name", initial: f.name },
      confirmLabel: "Rename",
    });
    if (!name?.trim() || name.trim() === f.name) return;
    setError(null);
    start(async () => {
      const r = await renameFolder(workspaceId, f.id, name);
      if (r.error) setError(r.error);
    });
  };
  const remove = async (f: ListFolder, count: number) => {
    const ok = await confirm({
      title: `Delete the folder “${f.name}”?`,
      body:
        count > 0
          ? `The ${plural(count, noun)} in it stay${count === 1 ? "s" : ""}, back in No folder.`
          : "It is empty.",
      confirmLabel: "Delete folder",
      danger: true,
    });
    if (!ok) return;
    setError(null);
    start(async () => {
      const r = await deleteFolder(workspaceId, f.id);
      if (r.error) setError(r.error);
    });
  };

  const words = query.trim().toLowerCase();
  const hit = (e: FolderEntry) =>
    !words || e.text.toLowerCase().includes(words);
  const inFolder = new Set(shown.flatMap((f) => f.items ?? []));
  const loose = entries.filter((e) => !inFolder.has(e.id));
  const byId = new Map(entries.map((e) => [e.id, e]));

  const drop = (folder: number | null) => ({
    onDragOver: (event: DragEvent) => {
      if (!event.dataTransfer.types.includes(DRAG)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      setOver(folder ?? "none");
    },
    onDragLeave: () => {
      setOver(null);
    },
    onDrop: (event: DragEvent) => {
      const item = Number(event.dataTransfer.getData(DRAG));
      setOver(null);
      if (!item) return;
      event.preventDefault();
      move(item, folder);
    },
  });

  const row = (e: FolderEntry) => (
    <li
      key={e.id}
      id={e.rowId}
      draggable
      onDragStart={(event) => {
        event.dataTransfer.setData(DRAG, String(e.id));
        event.dataTransfer.effectAllowed = "move";
      }}
      className={rowClassName}
    >
      {e.node}
    </li>
  );

  const list = (items: FolderEntry[], inside: boolean, tail?: ReactNode) =>
    variant === "cards" ? (
      <ul className="goal-projects" style={gridStyle?.(items.length)}>
        {items.map(row)}
        {tail}
      </ul>
    ) : (
      <ul
        className={cn(
          "divide-y divide-line",
          inside ? "border-t border-line" : PANEL,
        )}
      >
        {items.map(row)}
      </ul>
    );

  if (entries.length === 0 && shown.length === 0 && empty) {
    return (
      <>
        {empty}
        {after && variant === "cards" && list([], false, after)}
      </>
    );
  }

  const shared: Shared = {
    folders: shown,
    folderOf,
    move,
    makeAndMove: (item) => {
      void newFolder(item);
    },
  };
  const searching = words.length > 0;
  const looseShown = loose.filter(hit);

  return (
    <FolderContext value={shared}>
      {dialog}
      <div className="flex flex-col gap-3">
        {toolbar && (
          <div className="flex flex-wrap items-center gap-2">
            {entries.length > 0 && (
              <Input
                type="search"
                value={query}
                placeholder={`Find ${an(noun)}`}
                aria-label={`Find ${an(noun)}`}
                className="h-8 w-56 text-xs"
                onChange={(e) => {
                  setQuery(e.target.value);
                }}
              />
            )}
            <button
              type="button"
              className="ml-auto inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-sm text-ink-2 hover:bg-sunken hover:text-ink [&_svg]:size-3.5"
              onClick={() => {
                void newFolder();
              }}
            >
              <PlusIcon /> New folder
            </button>
          </div>
        )}
        <FormStatus error={error} className="text-xs" />
        {shown.map((f) => {
          const inside = (f.items ?? [])
            .filter((i) => ids.has(i))
            .map((i) => byId.get(i))
            .filter((e): e is FolderEntry => e !== undefined);
          const matches = inside.filter(hit);
          if (searching && matches.length === 0) return null;
          if (hideEmpty && inside.length === 0 && (f.items ?? []).length > 0)
            return null;
          const open = searching || !folded.has(f.id);
          const body = `folder-${kind}-${String(f.id)}`;
          return (
            <section
              key={f.id}
              aria-label={`Folder ${f.name}`}
              {...drop(f.id)}
              className={cn(
                "transition-shadow",
                variant === "rows" && `overflow-hidden ${PANEL}`,
                over === f.id && "ring-2 ring-accent/40",
                variant === "cards" && over === f.id && "rounded-2xl",
              )}
            >
              <div
                className={cn(
                  "flex items-center gap-2",
                  variant === "rows" ? "px-5 py-2.5" : "py-1",
                )}
              >
                <button
                  type="button"
                  aria-expanded={open}
                  aria-controls={body}
                  className="flex min-w-0 flex-1 items-center gap-2 text-left text-sm font-medium text-ink"
                  onClick={() => {
                    if (!searching) toggle(f.id);
                  }}
                >
                  <svg
                    aria-hidden
                    viewBox="0 0 12 12"
                    className={cn(
                      "size-3 shrink-0 text-ink-3 transition-transform duration-150",
                      !open && "-rotate-90",
                    )}
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M3 4.5 6 7.5 9 4.5" />
                  </svg>
                  <FolderIcon />
                  <span className="truncate">{f.name}</span>
                  <span className="text-xs font-normal text-ink-3 tabular-nums">
                    {searching
                      ? `${String(matches.length)} of ${String(inside.length)}`
                      : inside.length}
                  </span>
                </button>
                <button
                  type="button"
                  className="text-xs text-ink-3 hover:text-ink"
                  onClick={() => {
                    void rename(f);
                  }}
                >
                  Rename
                </button>
                <button
                  type="button"
                  className="text-xs text-ink-3 hover:text-danger"
                  onClick={() => {
                    void remove(f, inside.length);
                  }}
                >
                  Delete
                </button>
              </div>
              {open && (
                <div id={body}>
                  {matches.length > 0 ? (
                    list(matches, true)
                  ) : (
                    <p
                      className={cn(
                        "text-xs text-ink-3",
                        variant === "rows"
                          ? "border-t border-line px-5 py-3"
                          : "pb-2",
                      )}
                    >
                      Empty. Use “Move” on {an(noun)}, or drag one here.
                    </p>
                  )}
                </div>
              )}
            </section>
          );
        })}
        {(looseShown.length > 0 || (!searching && after)) && (
          <section
            aria-label="No folder"
            {...drop(null)}
            className={cn(
              "flex flex-col gap-2 rounded-2xl transition-shadow",
              over === "none" && "ring-2 ring-accent/40",
            )}
          >
            {shown.length > 0 && (
              <p className="px-1 text-xs font-medium text-ink-3">
                No folder{" "}
                <span className="tabular-nums">· {looseShown.length}</span>
              </p>
            )}
            {(looseShown.length > 0 || after) &&
              list(looseShown, false, searching ? undefined : after)}
          </section>
        )}
        {searching &&
          looseShown.length === 0 &&
          !shown.some((f) =>
            (f.items ?? []).some((i) => {
              const e = byId.get(i);
              return e !== undefined && hit(e);
            }),
          ) && (
            <p className="text-sm text-ink-3">
              No {noun} matches “{query.trim()}”.
            </p>
          )}
      </div>
    </FolderContext>
  );
}

function FolderIcon() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 16 16"
      className="size-4 shrink-0 text-ink-3"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinejoin="round"
    >
      <path d="M2 4.5A1.5 1.5 0 0 1 3.5 3h2.6l1.5 1.5h4.9A1.5 1.5 0 0 1 14 6v5.5a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 2 11.5z" />
    </svg>
  );
}
