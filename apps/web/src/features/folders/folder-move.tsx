"use client";

import { use, useState, useTransition } from "react";
import type { FolderKind } from "@/data/types";
import { cn } from "@/shared/ui/cn";
import { useAsk } from "@/shared/ui/confirm";
import { FormStatus } from "@/shared/ui/form-status";
import { PlusIcon } from "@/shared/ui/icons";
import { createFolder } from "./actions";
import { FolderContext } from "./folder-list";
import { MenuBackdrop } from "@/shared/ui/menu-backdrop";
import { Panel } from "@/shared/ui/panel";

/** A row's “Move” menu: No folder, each folder of its list, or a new one. */
export function MoveToFolder({
  item,
  className,
}: {
  item: number;
  className?: string;
}) {
  const shared = use(FolderContext);
  const [open, setOpen] = useState(false);
  if (!shared) return null;
  const current = shared.folderOf(item);
  const pick = (folder: number | null) => {
    setOpen(false);
    shared.move(item, folder);
  };
  return (
    <span className={cn("relative", className)}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        className="text-sm text-ink-2 hover:text-ink"
        onClick={() => {
          setOpen((o) => !o);
        }}
      >
        Move
      </button>
      {open && (
        <>
          <MenuBackdrop onClose={() => setOpen(false)} />
          <Panel
            role="menu"
            aria-label="Move to folder"
            tabIndex={-1}
            onKeyDown={(e) => {
              if (e.key === "Escape") setOpen(false);
            }}
            className="absolute top-7 right-0 z-30 w-56 p-1.5 shadow-popover"
          >
            <p className="px-3 pt-1 pb-1.5 text-xs text-ink-3">
              Move to folder
            </p>
            {[
              { id: null, name: "No folder" },
              ...shared.folders.map((f) => ({ id: f.id, name: f.name })),
            ].map((f) => (
              <button
                key={f.id ?? "none"}
                type="button"
                role="menuitemradio"
                aria-checked={current === f.id}
                className="flex w-full items-center justify-between gap-2 rounded-xl px-3 py-2 text-left text-sm text-ink hover:bg-canvas"
                onClick={() => {
                  pick(f.id);
                }}
              >
                <span className="truncate">{f.name}</span>
                {current === f.id && (
                  <span aria-hidden className="text-accent">
                    ✓
                  </span>
                )}
              </button>
            ))}
            <button
              type="button"
              role="menuitem"
              className="flex w-full items-center gap-1.5 rounded-xl px-3 py-2 text-left text-sm text-ink-2 hover:bg-canvas [&_svg]:size-3.5"
              onClick={() => {
                setOpen(false);
                shared.makeAndMove(item);
              }}
            >
              <PlusIcon /> New folder…
            </button>
          </Panel>
        </>
      )}
    </span>
  );
}

/** “+ Folder” for a page's own header (a goal's Projects line). */
export function NewFolderButton({
  workspaceId,
  kind,
  noun,
  className,
}: {
  workspaceId: string;
  kind: FolderKind;
  noun: string;
  className?: string;
}) {
  const { dialog, ask } = useAsk();
  const [busy, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  return (
    <>
      {dialog}
      <button
        type="button"
        disabled={busy}
        className={className}
        onClick={() => {
          void (async () => {
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
              if (r.error) setError(r.error);
            });
          })();
        }}
      >
        <PlusIcon /> Folder
      </button>
      <FormStatus error={error} className="w-full text-xs" />
    </>
  );
}
