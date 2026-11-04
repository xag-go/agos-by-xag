"use client";

import { useEffect, useState, useTransition } from "react";
import type { Proposal } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { Textarea } from "@/shared/ui/field";
import { type Kit, sentKit } from "@/features/workers/kit-types";
import { type Choice, decideProposal } from "./actions";
import type { HireModel } from "./hire-model";
import { HireDetails } from "./proposal-details/hire";
import type {
  GoalPayload,
  HirePayload,
  InstructionsPayload,
  PlanPayload,
  SkillPayload,
} from "./proposal-types";
import { InstructionsDetails } from "./proposal-details/instructions";
import { PlanDetails } from "./proposal-details/plan";
import { GoalDetails } from "./proposal-details/goal";
import { SkillDetails } from "./proposal-details/skill";
import { typing } from "@/shared/keyboard";
import { Eyebrow } from "@/shared/ui/eyebrow";
import { AttentionBadge } from "@/shared/ui/attention-badge";

/** What the owner is told once a decision landed (the Inbox's toast). */
export type Decided = {
  id: number;
  choice: Choice;
  kind: Proposal["kind"];
  label: string;
  /** An approved hire can be undone (the member is removed). */
  canUndo: boolean;
};

const KIND_LABEL: Record<Proposal["kind"], string> = {
  hire: "Hire",
  instructions: "Instructions change",
  plan: "Plan",
  goal: "Plan change",
  skill: "New skill",
  kit: "Kit",
};

/**
 * One proposal waiting for the owner: its payload rendered per kind, then
 * Approve / Revise (with a note) / Reject. Used by the Inbox and, for a hire,
 * by the Team chart's ghost card.
 */
export function ProposalCard({
  workspaceId,
  proposal: p,
  onDecided,
  compact = false,
  focused = false,
}: {
  workspaceId: string;
  proposal: Proposal;
  onDecided?: (decided: Decided) => void;
  /** Inside the org chart's box: no frame, fewer words. */
  compact?: boolean;
  /** The Inbox's keyboard focus (j / k): `a` approves, `r` rejects. */
  focused?: boolean;
}) {
  const [busy, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [revising, setRevising] = useState(false);
  const [note, setNote] = useState("");
  const [done, setDone] = useState<string | null>(null);
  // The owner's edits of a plan proposal, sent with the approve.
  const [edits, setEdits] = useState<Record<string, unknown>>({});
  const daily = p.kind === "goal" && p.payload.change === "daily_plan";

  const decide = (choice: Choice) =>
    start(async () => {
      setError(null);
      const r = await decideProposal(
        workspaceId,
        p.id,
        choice,
        note,
        choice === "approve"
          ? (p.kind === "hire" || p.kind === "kit") && edits.kit
            ? {
                kit: sentKit(edits.kit as Kit),
                // His model pick (only when the picker was shown).
                ...("model" in edits ? { model: edits.model } : {}),
              }
            : edits
          : undefined,
      );
      if (r.error) {
        setError(r.error);
        return;
      }
      setDone(
        choice === "approve"
          ? daily
            ? "Accepted: today's cards are on the Kanban."
            : "Approved."
          : choice === "revise"
            ? "Sent back with your note."
            : daily
              ? "Skipped."
              : "Rejected.",
      );
      onDecided?.({
        id: p.id,
        choice,
        kind: p.kind,
        label: p.label,
        canUndo: Boolean(r.proposal?.canUndo),
      });
    });
  useEffect(() => {
    if (!focused || done) return;
    const onKey = (e: KeyboardEvent) => {
      if (typing(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "a" && p.problems.length === 0) decide("approve");
      else if (e.key === "r") decide("reject");
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  });

  return (
    <div
      className={cn(
        !compact && "rounded-2xl border bg-panel px-4 py-3",
        !compact && (focused ? "border-ink" : "border-line"),
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Eyebrow>
            {KIND_LABEL[p.kind]} · from {p.memberName} · card {p.card}
            {p.round > 1 && ` · round ${String(p.round)}`}
          </Eyebrow>
          <p className="mt-0.5 font-display text-15 font-semibold text-ink">
            {p.label}
          </p>
        </div>
        <AttentionBadge shrink>Waiting for you</AttentionBadge>
      </div>

      <div className="mt-2">
        {(p.kind === "hire" || p.kind === "kit") && (
          <HireDetails
            forMember={p.kind === "kit"}
            workspaceId={workspaceId}
            payload={p.payload as HirePayload}
            serves={p.serves ?? null}
            choices={p.modelChoices ?? null}
            editing={
              edits.kit
                ? {
                    kit: edits.kit as Kit,
                    model:
                      "model" in edits
                        ? (edits.model as HireModel)
                        : ((p.payload as HirePayload).model ?? null),
                  }
                : null
            }
            onEdit={
              compact || done
                ? undefined
                : (next) => {
                    setEdits(
                      next
                        ? p.modelChoices
                          ? { kit: next.kit, model: next.model }
                          : { kit: next.kit }
                        : {},
                    );
                  }
            }
          />
        )}
        {p.kind === "instructions" && (
          <InstructionsDetails payload={p.payload as InstructionsPayload} />
        )}
        {p.kind === "plan" && (
          <PlanDetails payload={p.payload as PlanPayload} compact={compact} />
        )}
        {p.kind === "goal" && (
          <GoalDetails
            payload={p.payload as GoalPayload}
            edits={edits}
            onEdit={compact || done ? undefined : setEdits}
          />
        )}
        {p.kind === "skill" && (
          <SkillDetails payload={p.payload as SkillPayload} />
        )}
      </div>

      {p.problems.length > 0 && (
        <p className="mt-2 text-sm text-danger">
          Can&apos;t be approved as is: {p.problems.join("; ")}. Ask for
          changes.
        </p>
      )}
      {error && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {error}
        </p>
      )}

      {done ? (
        <p className="mt-3 text-sm text-ink-2">{done}</p>
      ) : revising ? (
        <form
          className="mt-3 flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            decide("revise");
          }}
        >
          <Textarea
            rows={2}
            value={note}
            onChange={(e) => {
              setNote(e.target.value);
            }}
            placeholder="What should change?"
            autoFocus
          />
          <div className="flex items-center gap-2">
            <Button type="submit" variant="primary" disabled={busy}>
              {busy ? "Sending…" : "Send back"}
            </Button>
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => {
                setRevising(false);
              }}
            >
              Cancel
            </Button>
          </div>
        </form>
      ) : (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button
            variant="primary"
            disabled={busy || p.problems.length > 0}
            onClick={() => {
              decide("approve");
            }}
          >
            {busy
              ? "Working…"
              : daily
                ? "Accept"
                : Object.keys(edits).length > 0
                  ? "Approve as edited"
                  : "Approve"}
          </Button>
          {p.kind !== "skill" && (
            <Button
              disabled={busy}
              onClick={() => {
                setRevising(true);
              }}
            >
              {daily ? "Change" : "Revise"}
            </Button>
          )}
          <Button
            variant="ghost"
            disabled={busy}
            className="text-danger hover:text-danger"
            onClick={() => {
              decide("reject");
            }}
          >
            {daily ? "Skip" : "Reject"}
          </Button>
        </div>
      )}
    </div>
  );
}
