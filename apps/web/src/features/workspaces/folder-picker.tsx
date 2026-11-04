"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import type { FolderListing } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { browseFolders } from "./actions";
import { PANEL } from "@/shared/ui/panel";

/**
 * The app's own folder picker: walk this machine's folders and pick one.
 * (The system picker can't give a web page the folder's real path.)
 */
export function FolderPicker({
  open,
  onPick,
  onClose,
}: {
  open: boolean;
  onPick: (path: string) => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [listing, setListing] = useState<FolderListing | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();

  const go = (path: string | null) => {
    start(async () => {
      const r = await browseFolders(path);
      if (r.error || !r.listing) {
        setError(r.error ?? "This folder can't be opened.");
        return;
      }
      setError(null);
      setListing(r.listing);
      setSelected(null);
    });
  };

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      d.showModal();
      if (!listing) go(null);
    } else if (!open && d.open) d.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const current = listing?.path ?? "";
  const crumbs = current.split("/").filter(Boolean);
  const chosen = selected ?? current;
  const chosenEntry =
    listing?.folders.find((f) => f.path === selected) ??
    listing?.places.find((p) => p.path === current);
  const canAdd = selected
    ? (listing?.folders.find((f) => f.path === selected)?.canAdd ?? false)
    : listing !== null &&
      current !== listing.home &&
      current !== "/" &&
      (chosenEntry?.canAdd ?? true);

  return (
    <dialog
      ref={ref}
      aria-label="Choose a folder"
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
      className={`${PANEL} m-auto w-[calc(100%-2rem)] max-w-3xl p-0 text-ink shadow-2xl`}
    >
      <div className="flex h-[min(34rem,80vh)] flex-col">
        <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-3">
          <h2 className="font-display text-lg font-semibold">
            Choose a folder
          </h2>
          <Button type="button" variant="ghost" onClick={onClose}>
            Close
          </Button>
        </div>
        <div className="flex min-h-0 flex-1">
          <nav
            aria-label="Places"
            className="hidden w-44 shrink-0 flex-col gap-0.5 overflow-y-auto border-r border-line p-2 sm:flex"
          >
            {listing?.places.map((p) => (
              <button
                key={p.path}
                type="button"
                onClick={() => {
                  go(p.path);
                }}
                className={cn(
                  "truncate rounded-lg px-2.5 py-1.5 text-left text-sm",
                  current === p.path
                    ? "bg-sunken font-medium text-ink"
                    : "text-ink-2 hover:bg-sunken/60 hover:text-ink",
                )}
              >
                {p.name}
              </button>
            ))}
          </nav>
          <div className="flex min-w-0 flex-1 flex-col">
            <div className="flex flex-wrap items-center gap-1 border-b border-line px-4 py-2 text-sm">
              <button
                type="button"
                disabled={!listing?.parent || busy}
                onClick={() => {
                  go(listing?.parent ?? null);
                }}
                className="mr-1 rounded-md px-2 py-0.5 text-ink-2 hover:bg-sunken disabled:opacity-40"
                aria-label="Up one folder"
              >
                ↑
              </button>
              <button
                type="button"
                className="text-ink-3 hover:text-ink"
                onClick={() => {
                  go("/");
                }}
              >
                /
              </button>
              {crumbs.map((c, i) => (
                <span
                  key={`${String(i)}-${c}`}
                  className="flex items-center gap-1"
                >
                  <button
                    type="button"
                    className={cn(
                      "hover:text-ink",
                      i === crumbs.length - 1 ? "font-medium" : "text-ink-3",
                    )}
                    onClick={() => {
                      go("/" + crumbs.slice(0, i + 1).join("/"));
                    }}
                  >
                    {c}
                  </button>
                  {i < crumbs.length - 1 && (
                    <span className="text-ink-3">/</span>
                  )}
                </span>
              ))}
            </div>
            <ul
              aria-label="Folders"
              className={cn(
                "min-h-0 flex-1 overflow-y-auto p-2",
                busy && "opacity-60",
              )}
            >
              {listing && listing.folders.length === 0 && (
                <li className="px-3 py-6 text-center text-sm text-ink-3">
                  No folders in here.
                </li>
              )}
              {listing?.folders.map((f) => (
                <li key={f.path}>
                  <button
                    type="button"
                    title={
                      f.canAdd
                        ? f.path
                        : "Holds private data: open it and pick a folder inside"
                    }
                    onClick={() => {
                      setSelected(f.path);
                    }}
                    onDoubleClick={() => {
                      go(f.path);
                    }}
                    className={cn(
                      "flex w-full items-center gap-2.5 rounded-lg px-3 py-1.5 text-left text-sm",
                      selected === f.path
                        ? "bg-accent/15 text-ink"
                        : "hover:bg-sunken/60",
                    )}
                  >
                    <FolderGlyph />
                    <span className="min-w-0 flex-1 truncate">{f.name}</span>
                    <span
                      className="text-xs text-ink-3"
                      onClick={(e) => {
                        e.stopPropagation();
                        go(f.path);
                      }}
                    >
                      Open ›
                    </span>
                  </button>
                </li>
              ))}
              {listing?.truncated && (
                <li className="px-3 py-2 text-xs text-ink-3">
                  Only the first 500 folders are shown.
                </li>
              )}
            </ul>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-3">
          <p
            className="min-w-0 flex-1 truncate text-sm text-ink-2"
            title={chosen}
          >
            {error ? (
              <span className="text-danger">{error}</span>
            ) : (
              chosen || "…"
            )}
          </p>
          <div className="flex gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              disabled={!canAdd || busy || !chosen}
              onClick={() => {
                onPick(chosen);
              }}
            >
              Choose this folder
            </Button>
          </div>
        </div>
      </div>
    </dialog>
  );
}

function FolderGlyph() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 20 20"
      className="size-4 shrink-0 fill-current text-accent"
    >
      <path d="M2 5.5A1.5 1.5 0 0 1 3.5 4h4l1.6 1.8h7.4A1.5 1.5 0 0 1 18 7.3v7.2a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 2 14.5z" />
    </svg>
  );
}
