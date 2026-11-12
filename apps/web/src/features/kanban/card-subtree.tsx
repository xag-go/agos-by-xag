"use client";

import { useState } from "react";
import type { KanbanCardDetail, KanbanHold } from "@/data/types";
import { holdSubtree, resumeHold } from "@/features/inbox/actions";
import { watchTree } from "@/features/setup/actions";
import { Button } from "@/shared/ui/button";

/**
 * Pause / Resume / Cancel the card and everything under it (its children on
 * Hermes's Kanban, task_links): one hold in the core, Hermes's own schedule /
 * unblock / archive on each card. Shown when the card has children or is
 * paused; Cancel asks first (Hermes has no unarchive).
 */
export function SubtreeControls({
  workspaceId,
  card,
  busy,
  run,
}: {
  workspaceId: string;
  card: KanbanCardDetail;
  busy: boolean;
  run: (task: () => Promise<{ error: string | null }>, ok?: () => void) => void;
}) {
  const [said, setSaid] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const open = !["done", "archived"].includes(card.status);
  const holdId = card.holdId ?? null;
  const watched = (card.watchdogId ?? null) !== null;
  if (card.children.length === 0 && holdId === null && !watched) return null;
  const words = (hold: KanbanHold | undefined, verb: string) => {
    if (!hold) return `${verb}.`;
    const left = hold.left ?? [];
    const released = hold.released ?? [];
    return (
      `${verb} ${String(hold.held.length)} card${hold.held.length === 1 ? "" : "s"}` +
      (left.length > 0 ? ` (left as they are: ${left.join(", ")})` : "") +
      (released.length > 0 ? `: ${released.join(", ")}` : "") +
      "."
    );
  };
  return (
    <div className="mt-3 flex flex-col gap-2 border-t border-line pt-3">
      <p className="text-11 font-medium tracking-caps text-ink-3 uppercase">
        This card and its {String(card.children.length)} under it
      </p>
      <div className="flex flex-wrap gap-2">
        {holdId === null && open && (
          <Button
            type="button"
            disabled={busy}
            onClick={() => {
              run(async () => {
                const r = await holdSubtree(workspaceId, card.id, "pause");
                if (!r.error) setSaid(words(r.hold, "Paused"));
                return r;
              });
            }}
          >
            Pause subtree
          </Button>
        )}
        {holdId !== null && (
          <Button
            type="button"
            variant="primary"
            disabled={busy}
            onClick={() => {
              run(async () => {
                const r = await resumeHold(workspaceId, holdId);
                if (!r.error) setSaid(words(r.hold, "Resumed"));
                return r;
              });
            }}
          >
            Resume
          </Button>
        )}
        {open && !confirming && (
          <Button
            type="button"
            variant="danger"
            disabled={busy}
            onClick={() => {
              setConfirming(true);
            }}
          >
            Cancel subtree
          </Button>
        )}
        {(open || watched) && (
          <Button
            type="button"
            disabled={busy}
            aria-pressed={watched}
            title="A scheduled job (the Co-Founder, every 30 min) checks this tree: when it stopped with open cards left, it wakes once per stop to continue or reopen them, and asks you after three stops with no progress."
            onClick={() => {
              run(async () => {
                const r = await watchTree(workspaceId, card.id, !watched);
                if (!r.error)
                  setSaid(
                    watched ? "No longer watched." : "Watching this tree.",
                  );
                return r;
              });
            }}
          >
            {watched ? "Stop watching" : "Watch this tree"}
          </Button>
        )}
        {confirming && (
          <>
            <span className="self-center text-sm text-ink-2">
              Archive this card and every open card under it? There is no undo
              for that.
            </span>
            <Button
              type="button"
              variant="danger"
              disabled={busy}
              onClick={() => {
                setConfirming(false);
                run(async () => {
                  const r = await holdSubtree(workspaceId, card.id, "cancel");
                  if (!r.error) setSaid(words(r.hold, "Cancelled"));
                  return r;
                });
              }}
            >
              Yes, cancel all
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setConfirming(false);
              }}
            >
              Keep
            </Button>
          </>
        )}
      </div>
      {said && <p className="text-sm text-ink-2">{said}</p>}
    </div>
  );
}
