"use client";

import { useState, useTransition } from "react";
import type {
  KanbanBoard,
  KanbanCardDetail,
  ReviewChip,
  ReviewFlow,
  ReviewNote,
} from "@/data/types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { Field, Input, Select, Textarea } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { decideReview, setReviewRules } from "./card-actions";

type Members = KanbanBoard["members"];
type Decision = "approve" | "changes" | "reassign" | "drop";

type Stage = NonNullable<ReviewFlow["stages"]>[number];

const STATE_WORDS: Record<Stage["state"], string> = {
  waiting: "Waiting",
  current: "Reviewing now",
  approved: "Approved",
  changes: "Changes asked",
  skipped: "Skipped",
  stuck: "Stuck",
};

const PLAN_WORDS: Record<ReviewFlow["plan"], string> = {
  none: "",
  needed: "A plan is needed before the work starts.",
  waiting: "The plan waits to be accepted.",
  changes: "The plan was sent back for changes.",
  accepted: "The plan is accepted: the work goes on.",
};

/** The Kanban chip's words: "Review 2/3 · round 1", "Plan waiting", "Stuck in review". */
export function reviewChipText(chip: ReviewChip | null | undefined): string {
  if (!chip) return "";
  if (chip.plan === "waiting") return "Plan waiting";
  if (chip.plan === "needed" || chip.plan === "changes") return "Plan first";
  if (chip.phase === "stuck")
    return `Stuck in review · round ${String(chip.round)}`;
  if (chip.phase === "review" && chip.stage > 0)
    return `Review ${String(chip.stage)}/${String(chip.stages)} · round ${String(chip.round)}`;
  if (chip.phase === "done") return "Reviewed";
  return chip.stages > 0 && chip.round > 1
    ? `Changes · round ${String(chip.round)}`
    : "";
}

const stageName = (stage: string, members: Members) => {
  if (stage === "lead") return "The member's lead";
  if (stage === "cofounder") return "The Co-Founder";
  if (stage === "owner") return "You (the owner)";
  return members.find((m) => m.name === stage)?.title ?? `@${stage}`;
};

/** An ordered list of review stages: lead / Co-Founder / owner / a member. */
export function StagesEditor({
  stages,
  members,
  onChange,
  disabled,
}: {
  stages: string[];
  members: Members;
  onChange: (stages: string[]) => void;
  disabled?: boolean;
}) {
  const options = [
    "lead",
    "cofounder",
    "owner",
    ...members.map((m) => m.name).filter((n) => n !== "cofounder"),
  ];
  return (
    <div className="flex flex-col gap-2">
      {stages.length === 0 && (
        <p className="text-sm text-ink-3">
          No review: a card is done when its member finishes it.
        </p>
      )}
      <ol className="flex flex-col gap-2">
        {stages.map((stage, i) => (
          <li key={`${stage}-${String(i)}`} className="flex items-center gap-2">
            <span className="w-5 text-right text-xs text-ink-3">
              {String(i + 1)}.
            </span>
            <Select
              aria-label={`Stage ${String(i + 1)}`}
              value={stage}
              disabled={disabled}
              onChange={(e) => {
                const next = [...stages];
                next[i] = e.currentTarget.value;
                onChange(next);
              }}
            >
              {options.map((o) => (
                <option key={o} value={o}>
                  {stageName(o, members)}
                </option>
              ))}
            </Select>
            <Button
              variant="ghost"
              aria-label={`Remove stage ${String(i + 1)}`}
              disabled={disabled}
              onClick={() => {
                onChange(stages.filter((_s, j) => j !== i));
              }}
            >
              Remove
            </Button>
          </li>
        ))}
      </ol>
      {stages.length < 6 && (
        <Button
          className="self-start"
          disabled={disabled}
          onClick={() => {
            onChange([...stages, stages.length === 0 ? "lead" : "owner"]);
          }}
        >
          Add a stage
        </Button>
      )}
    </div>
  );
}

function Notes({ notes }: { notes: ReviewNote[] }) {
  if (notes.length === 0) return null;
  const verb = (n: ReviewNote) =>
    ({
      submit: "Handed to review",
      approve: "Approved",
      changes: "Changes asked",
      stuck: "Changes asked (round cap reached)",
      reset: "Sent back by the owner",
      pass: "Approved by the owner",
      ready: "Plan ready",
      accept: "Plan accepted",
    })[n.verb] ?? n.verb;
  return (
    <ol className="flex flex-col gap-2">
      {notes.map((n, i) => (
        <li
          key={`${String(n.at)}-${String(i)}`}
          className="rounded-lg bg-sunken px-3 py-2 text-sm"
        >
          <p className="text-xs text-ink-3">
            {verb(n)}
            {n.kind === "review" && n.stage > 0
              ? ` · stage ${String(n.stage)}`
              : ""}
            {n.kind === "plan" ? ` · plan v${String(n.revision)}` : ""}
            {n.kind === "review" ? ` · round ${String(n.round)}` : ""}
          </p>
          {n.text && (
            <p className="mt-1 whitespace-pre-wrap text-ink-2">{n.text}</p>
          )}
        </li>
      ))}
    </ol>
  );
}

/** His buttons on a review waiting for him (the card's tab and the Inbox). */
export function ReviewDecisions({
  workspaceId,
  cardId,
  can,
  members,
  plan,
}: {
  workspaceId: string;
  cardId: string;
  can: Decision[];
  members: Members;
  plan?: boolean;
}) {
  const [busy, start] = useTransition();
  const [note, setNote] = useState("");
  const [member, setMember] = useState("");
  const [status, setStatus] = useState<{
    error: string | null;
    saved?: boolean;
  }>({
    error: null,
  });
  if (can.length === 0) return null;
  const run = (action: Decision) => {
    start(async () => {
      const r = await decideReview(workspaceId, cardId, action, note, member);
      setStatus(r);
      if (!r.error) setNote("");
    });
  };
  const stuck = can.includes("drop");
  return (
    <div className="flex flex-col gap-2">
      <Textarea
        aria-label="Your note"
        placeholder={
          stuck
            ? "A note for whoever takes it next (needed to send it back)"
            : "What to change (needed to request changes)"
        }
        value={note}
        disabled={busy}
        onChange={(e) => {
          setNote(e.currentTarget.value);
        }}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          disabled={busy}
          onClick={() => {
            run("approve");
          }}
        >
          {plan ? "Accept the plan" : "Approve"}
        </Button>
        <Button
          disabled={busy || !note.trim()}
          onClick={() => {
            run("changes");
          }}
        >
          {stuck ? "Send back" : "Request changes"}
        </Button>
        {can.includes("reassign") && (
          <>
            <Select
              aria-label="Give it to"
              className="w-auto"
              value={member}
              disabled={busy}
              onChange={(e) => {
                setMember(e.currentTarget.value);
              }}
            >
              <option value="">Give it to…</option>
              {members.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.title}
                </option>
              ))}
            </Select>
            <Button
              disabled={busy || !member}
              onClick={() => {
                run("reassign");
              }}
            >
              Reassign
            </Button>
          </>
        )}
        {stuck && (
          <Button
            variant="danger"
            disabled={busy}
            onClick={() => {
              run("drop");
            }}
          >
            Drop
          </Button>
        )}
      </div>
      <FormStatus error={status.error} saved={status.saved} savedText="Done." />
    </div>
  );
}

/** The card modal's Review tab: its stages with where each stands, the round,
 * the notes, the plan (opened in Documents, where passages take comments), his
 * buttons, and the card's own rules. */
export function ReviewTab({
  workspaceId,
  card,
  members,
  planHref,
}: {
  workspaceId: string;
  card: KanbanCardDetail;
  members: Members;
  planHref: string;
}) {
  const flow = card.review ?? null;
  const stages = flow?.stages ?? [];
  const ownerCan = flow?.ownerCan ?? [];
  const notes = flow?.notes ?? [];
  const label = "text-11 font-medium tracking-caps text-ink-3 uppercase";
  return (
    <div className="flex flex-col gap-6 px-6 py-5">
      {flow === null ? (
        <p className="text-sm text-ink-2">
          No review on this card: it is done when its member finishes it. Give
          it review stages or a plan first below.
        </p>
      ) : (
        <>
          {stages.length > 0 && (
            <section className="flex flex-col gap-3">
              <p className={label}>
                Review · round {String(flow.round)} of at most{" "}
                {String(flow.cap)}
              </p>
              <ol className="flex flex-col gap-2">
                {stages.map((s, i) => (
                  <li
                    key={`${s.stage}-${String(i)}`}
                    className="flex items-center justify-between gap-3 rounded-lg border border-line px-3 py-2 text-sm"
                  >
                    <span>
                      {String(i + 1)}. {s.label || stageName(s.stage, members)}
                    </span>
                    <span
                      className={cn(
                        "rounded-md px-1.5 py-0.5 text-xs font-medium",
                        s.state === "approved" && "bg-success/15 text-success",
                        s.state === "current" &&
                          "bg-attention text-attention-ink",
                        (s.state === "changes" || s.state === "stuck") &&
                          "bg-danger-soft text-danger",
                        (s.state === "waiting" || s.state === "skipped") &&
                          "bg-sunken text-ink-3",
                      )}
                    >
                      {STATE_WORDS[s.state]}
                    </span>
                  </li>
                ))}
              </ol>
            </section>
          )}
          {flow.plan !== "none" && (
            <section className="flex flex-col gap-2">
              <p className={label}>
                Plan
                {flow.planRevision > 0 ? ` v${String(flow.planRevision)}` : ""}
                {flow.planReviewerLabel
                  ? ` · accepted by ${flow.planReviewerLabel}`
                  : ""}
              </p>
              <p className="text-sm text-ink-2">{PLAN_WORDS[flow.plan]}</p>
              {flow.planRevision > 0 && (
                <a
                  href={planHref}
                  className="text-sm text-accent underline-offset-2 hover:underline"
                >
                  Open the plan (select a passage to comment on it)
                </a>
              )}
            </section>
          )}
          {ownerCan.length > 0 && (
            <section className="flex flex-col gap-2">
              <p className={label}>Your decision</p>
              <ReviewDecisions
                workspaceId={workspaceId}
                cardId={card.id}
                can={ownerCan}
                members={members}
                plan={flow.plan === "waiting"}
              />
            </section>
          )}
          {notes.length > 0 && (
            <section className="flex flex-col gap-2">
              <p className={label}>History</p>
              <Notes notes={notes} />
            </section>
          )}
        </>
      )}
      <RulesEditor workspaceId={workspaceId} card={card} members={members} />
    </div>
  );
}

function RulesEditor({
  workspaceId,
  card,
  members,
}: {
  workspaceId: string;
  card: KanbanCardDetail;
  members: Members;
}) {
  const flow = card.review ?? null;
  const [open, setOpen] = useState(false);
  const [stages, setStages] = useState<string[]>(
    (flow?.stages ?? []).map((s) => s.stage),
  );
  const [cap, setCap] = useState(String(flow?.cap ?? 3));
  const [plan, setPlan] = useState(flow !== null && flow.plan !== "none");
  const [planReviewer, setPlanReviewer] = useState(
    flow?.planReviewer || "owner",
  );
  const [busy, start] = useTransition();
  const [status, setStatus] = useState<{
    error: string | null;
    saved?: boolean;
  }>({
    error: null,
  });
  if (!open)
    return (
      <Button
        className="self-start"
        onClick={() => {
          setOpen(true);
        }}
      >
        {flow?.own
          ? "Edit this card's review rules"
          : "Set this card's review rules"}
      </Button>
    );
  const save = (reset: boolean) => {
    start(async () => {
      setStatus(
        await setReviewRules(
          workspaceId,
          card.id,
          reset
            ? { reset: true }
            : { stages, cap: Number(cap) || 3, plan, planReviewer },
        ),
      );
    });
  };
  return (
    <section className="flex flex-col gap-3 border-t border-line pt-4">
      <p className="text-sm font-medium">This card&apos;s review rules</p>
      <StagesEditor
        stages={stages}
        members={members}
        onChange={setStages}
        disabled={busy}
      />
      <Field label="Rounds of changes before it comes to you">
        <Input
          type="number"
          min={1}
          max={20}
          value={cap}
          disabled={busy}
          className="w-24"
          onChange={(e) => {
            setCap(e.currentTarget.value);
          }}
        />
      </Field>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={plan}
          disabled={busy}
          onChange={(e) => {
            setPlan(e.currentTarget.checked);
          }}
        />
        A plan first: the member writes a plan that must be accepted before the
        work
      </label>
      {plan && (
        <Field label="Who accepts the plan">
          <Select
            value={planReviewer}
            disabled={busy}
            onChange={(e) => {
              setPlanReviewer(e.currentTarget.value);
            }}
          >
            {["owner", "lead", "cofounder", ...members.map((m) => m.name)]
              .filter((v, i, all) => all.indexOf(v) === i)
              .map((o) => (
                <option key={o} value={o}>
                  {stageName(o, members)}
                </option>
              ))}
          </Select>
        </Field>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          variant="primary"
          disabled={busy}
          onClick={() => {
            save(false);
          }}
        >
          Save
        </Button>
        <Button
          variant="ghost"
          disabled={busy}
          onClick={() => {
            save(true);
          }}
        >
          Use the workspace&apos;s rules
        </Button>
      </div>
      <FormStatus error={status.error} saved={status.saved} />
    </section>
  );
}
