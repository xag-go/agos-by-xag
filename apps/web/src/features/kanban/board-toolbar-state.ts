"use client";

/** The board toolbar's state and saved-view actions, shared by its desktop row and
 * its phone layout (board-toolbar-mobile.tsx). Owns no markup. */

import { useState, useTransition } from "react";
import { deleteBoardView, saveBoardView } from "./board-actions";
import type { MobileToolbar } from "./board-toolbar-mobile";
import type { BoardQuery, SavedView } from "./views";

export type ToolbarProps = {
  workspaceId: string;
  q: BoardQuery;
  views: SavedView[];
  go: (q: BoardQuery) => void;
  shown: number;
  total: number;
  selecting: boolean;
  onSelecting: (on: boolean) => void;
};

export type ToolbarState = MobileToolbar & { error: string | null };

export function useToolbarState(p: ToolbarProps): ToolbarState {
  const { workspaceId, q, views, go } = p;
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
  const remove = (view: SavedView) => {
    start(async () => {
      const r = await deleteBoardView(workspaceId, view.id);
      setError(r.error);
      if (!r.error) go({ ...q, view: null });
    });
  };
  return {
    ...p,
    busy,
    error,
    naming,
    setNaming,
    open,
    setOpen,
    current,
    set,
    save,
    remove,
  };
}
