"use client";

import { useState, useTransition } from "react";
import type { CofounderAction } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { decideCofounderAction } from "./actions";
import { Panel } from "@/shared/ui/panel";

const STATUS: Record<CofounderAction["status"], string> = {
  proposed: "Waiting for you",
  done: "Done",
  rejected: "Refused",
  failed: "Didn't work",
  undone: "Undone",
};

/** Something the Co-Founder did for the owner (or asks to do, in ask mode). */
export function ActionCard({
  workspaceId,
  action: a,
}: {
  workspaceId: string;
  action: CofounderAction;
}) {
  const [busy, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const decide = (choice: "approve" | "reject" | "undo") =>
    start(async () => {
      setError(null);
      const r = await decideCofounderAction(workspaceId, a.id, choice);
      if (r.error) setError(r.error);
    });
  return (
    <Panel className="max-w-xl px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium">{a.title}</p>
        <span
          className={cn(
            "shrink-0 rounded-md px-1.5 py-0.5 text-xs font-medium",
            a.status === "proposed" && "bg-attention text-attention-ink",
            a.status === "done" && "bg-sunken text-ink-2",
            (a.status === "rejected" || a.status === "undone") &&
              "bg-sunken text-ink-3",
            a.status === "failed" && "bg-danger-soft text-danger",
          )}
        >
          {STATUS[a.status]}
        </span>
      </div>
      {a.detail && <Detail text={a.detail} />}
      {a.status === "failed" && a.error && (
        <p className="mt-1 text-sm text-danger">{a.error}</p>
      )}
      {error && (
        <p role="alert" className="mt-1 text-sm text-danger">
          {error}
        </p>
      )}
      {(a.status === "proposed" || a.status === "failed" || a.canUndo) && (
        <div className="mt-3 flex items-center gap-2">
          {a.status !== "done" && (
            <Button
              type="button"
              variant="primary"
              disabled={busy}
              onClick={() => {
                decide("approve");
              }}
            >
              {busy
                ? "Working…"
                : a.status === "failed"
                  ? "Try again"
                  : "Approve"}
            </Button>
          )}
          {a.status === "proposed" && (
            <Button
              type="button"
              variant="ghost"
              disabled={busy}
              onClick={() => {
                decide("reject");
              }}
            >
              No
            </Button>
          )}
          {a.canUndo && (
            <Button
              type="button"
              variant="ghost"
              disabled={busy}
              onClick={() => {
                decide("undo");
              }}
            >
              {busy ? "Working…" : "Undo"}
            </Button>
          )}
        </div>
      )}
    </Panel>
  );
}

/** The card's text: three lines, then "Show all" (nothing is cut for good). */
function Detail({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > 240 || text.split("\n").length > 3;
  return (
    <div className="mt-1">
      <p
        className={cn(
          "text-sm whitespace-pre-line text-ink-2",
          !open && "line-clamp-3",
        )}
      >
        {text}
      </p>
      {long && (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="mt-0.5 text-xs text-accent hover:underline"
        >
          {open ? "Show less" : "Show all"}
        </button>
      )}
    </div>
  );
}
