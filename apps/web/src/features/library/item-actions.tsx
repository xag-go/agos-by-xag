"use client";

import { useState, useTransition } from "react";
import type { LibraryItem } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { useAsk } from "@/shared/ui/confirm";
import { FormStatus } from "@/shared/ui/form-status";
import {
  applySkillUpdate,
  deleteLibraryItem,
  duplicateLibraryItem,
} from "./actions";

export function ItemActions({
  item,
  nameOf,
  workspaceId,
}: {
  item: LibraryItem;
  nameOf: (id: string) => string;
  workspaceId?: string;
}) {
  const [busy, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const { dialog, ask, confirm } = useAsk();
  return (
    <>
      {dialog}
      <button
        type="button"
        disabled={busy}
        className="text-ink-2 hover:text-ink"
        onClick={() => {
          void (async () => {
            const name = await ask({
              title: `Duplicate “${item.title}”`,
              body: "Name of the copy (lowercase letters, digits, dashes).",
              input: { label: "Name", initial: `${item.name}-copy` },
              confirmLabel: "Duplicate",
            });
            if (!name) return;
            start(async () => {
              const result = await duplicateLibraryItem(
                item.id,
                name,
                workspaceId,
                item.kind,
              );
              if (result.error) setError(result.error);
            });
          })();
        }}
      >
        Duplicate
      </button>
      <button
        type="button"
        disabled={busy}
        className="text-danger hover:underline"
        onClick={() => {
          void (async () => {
            const users = workspaceId ? [] : item.usedBy.map(nameOf);
            const ok = await confirm({
              title: `Delete “${item.title}”?`,
              body: users.length
                ? `It is on in: ${users.join(", ")}. Deleting turns it off there too.`
                : item.kind === "skill"
                  ? "The Co-Founder and the agents of this workspace stop using it. It is archived, so it can be restored."
                  : undefined,
              confirmLabel: "Delete",
              danger: true,
            });
            if (!ok) return;
            start(async () => {
              const result = await deleteLibraryItem(
                item.id,
                workspaceId,
                item.kind === "mcp" || item.kind === "skill"
                  ? item.kind
                  : "agent",
              );
              if (result.error) setError(result.error);
            });
          })();
        }}
      >
        Delete
      </button>
      <FormStatus error={error} className="w-full text-xs" />
    </>
  );
}

export function UpdateButton({
  itemId,
  workspaceId,
}: {
  itemId: number;
  workspaceId: string;
}) {
  const [busy, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  return (
    <span className="flex items-center gap-2">
      <Button
        className="h-8"
        disabled={busy}
        onClick={() => {
          start(async () => {
            const r = await applySkillUpdate(workspaceId, itemId);
            if (r.error) setError(r.error);
          });
        }}
      >
        {busy ? "Updating…" : "Update available"}
      </Button>
      <FormStatus error={error} className="text-xs" />
    </span>
  );
}
