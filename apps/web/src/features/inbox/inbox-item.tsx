"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import type { FounderTask, InboxItem } from "@/data/types";
import { answerCard } from "@/features/kanban/card-actions";
import { ReviewDecisions } from "@/features/kanban/card-review";
import { KanbanAskCard } from "@/features/chats/kanban-asks";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { Textarea } from "@/shared/ui/field";
import { ReadinessPanel } from "@/features/workers/readiness";
import { finishFounderTask } from "@/features/workers/actions";
import { HeldCard } from "./held-card";
import { type Decided, ProposalCard } from "./proposal-card";
import { QuestionCard } from "./question-card";
import { SkillRequestNote, SkillsImprovedNote } from "./skill-notes";
import { Eyebrow } from "@/shared/ui/eyebrow";

/** One of his own Founder tasks (a card on Hermes's Kanban the Co-Founder gave
 * him): what to do, and Done (Hermes completes it; the cards waiting go on). */
function FounderItem({
  workspaceId,
  task,
  focused,
  onDone,
}: {
  workspaceId: string;
  task: FounderTask;
  focused: boolean;
  onDone: (words: string) => void;
}) {
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  const what = task.body
    .split("\n\n")
    .filter((p) => !p.startsWith("This is the Founder's own task"))
    .join("\n\n")
    .trim();
  return (
    <div
      className={cn(
        "flex flex-col gap-3 rounded-2xl border bg-panel p-4",
        focused ? "border-ink" : "border-line",
      )}
    >
      <p className="font-medium [overflow-wrap:anywhere]">{task.title}</p>
      {what && (
        <p className="text-sm whitespace-pre-line text-pretty text-ink-2">
          {what}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <input
          aria-label="What you did (optional)"
          value={note}
          placeholder="What you did (optional)"
          onChange={(e) => {
            setNote(e.target.value);
          }}
          className="h-9 min-w-0 flex-1 rounded-lg border border-line bg-panel px-3 text-sm"
        />
        <Button
          variant="primary"
          disabled={busy}
          onClick={() => {
            setError(null);
            start(async () => {
              const r = await finishFounderTask(workspaceId, task.id, note);
              if (r.error) setError(r.error);
              else
                onDone(`Done: ${task.title}. The cards waiting on it go on.`);
            });
          }}
        >
          {busy ? "Saving…" : "Done"}
        </Button>
      </div>
      {error && <p className="text-sm text-danger">{error}</p>}
    </div>
  );
}

export const TYPE_LABEL: Record<InboxItem["type"], string> = {
  proposal: "Proposal",
  question: "Question",
  ask: "Needs your OK",
  review: "Review",
  blocked: "Blocked for you",
  attention: "Stalled",
  approval: "Approval in a chat",
  chain: "Team stalled",
  note: "Team note",
  mention: "Mentioned you",
  held: "Memory change",
  readiness: "Getting ready",
  founder: "For you to do",
};

export function Item({
  workspaceId,
  item,
  focused,
  onDecided,
  onAnswered,
  onDone,
}: {
  workspaceId: string;
  item: InboxItem;
  focused: boolean;
  onDecided: (d: Decided) => void;
  onAnswered: (label: string) => void;
  onDone: (words: string) => void;
}) {
  if (item.readiness)
    return (
      <div
        className={cn(
          "flex flex-col gap-3 rounded-2xl border bg-panel p-4",
          focused ? "border-ink" : "border-line",
        )}
      >
        <p className="font-medium">{item.title}</p>
        <ReadinessPanel
          workspaceId={workspaceId}
          member={item.readiness.member}
          initial={item.readiness}
        />
      </div>
    );
  if (item.founder)
    return (
      <FounderItem
        workspaceId={workspaceId}
        task={item.founder}
        focused={focused}
        onDone={onDone}
      />
    );
  if (item.held)
    return (
      <HeldCard
        workspaceId={workspaceId}
        held={item.held}
        focused={focused}
        onDecided={onDone}
      />
    );
  if (item.proposal)
    return (
      <ProposalCard
        workspaceId={workspaceId}
        proposal={item.proposal}
        onDecided={onDecided}
        focused={focused}
      />
    );
  if (item.question)
    return (
      <QuestionCard
        workspaceId={workspaceId}
        question={item.question}
        focused={focused}
        onAnswered={(_id, label) => {
          onAnswered(label);
        }}
      />
    );
  if (item.ask)
    return (
      <KanbanAskCard
        workspaceId={workspaceId}
        ask={item.ask}
        onAnswered={() => {
          onAnswered(item.title);
        }}
      />
    );
  if (item.review) {
    const r = item.review;
    const what =
      r.kind === "plan"
        ? `The plan (v${String(r.planRevision)}) waits for your accept. Open the card's plan to comment on passages.`
        : r.kind === "stuck"
          ? `Stuck in review after ${String(r.rounds)} rounds (cap ${String(r.cap)}): approve it as it is, send it back with a note, give it to someone else or drop it.`
          : `Stage ${String(r.stage)} of ${String(r.stages)} is yours · round ${String(r.round)}.`;
    const notes = (r.notes ?? []).filter((n) => n.text);
    return (
      <div
        className={cn(
          "flex flex-col gap-3 rounded-2xl border bg-panel p-4",
          focused ? "border-ink" : "border-line",
        )}
      >
        <p className="font-medium">{item.title || `Card ${item.card}`}</p>
        <p className="text-sm text-ink-2">{what}</p>
        {notes.length > 0 && (
          <ol className="flex flex-col gap-1 text-sm text-ink-2">
            {notes.slice(-6).map((n, i) => (
              <li key={`${String(n.at)}-${String(i)}`}>
                <span className="text-ink-3">
                  {n.kind === "plan"
                    ? `Plan v${String(n.revision)}`
                    : `Round ${String(n.round)}`}
                  :{" "}
                </span>
                {n.text}
              </li>
            ))}
          </ol>
        )}
        <ReviewDecisions
          workspaceId={workspaceId}
          cardId={item.card}
          can={r.ownerCan ?? []}
          members={r.members ?? []}
          plan={r.kind === "plan"}
        />
      </div>
    );
  }
  if (item.chain)
    return (
      <div
        className={cn(
          "max-w-xl rounded-2xl border bg-panel px-4 py-3",
          focused ? "border-ink" : "border-line",
        )}
      >
        <p className="text-sm font-medium">{item.title}</p>
        <ul className="mt-1 flex flex-col gap-0.5 text-sm text-ink-2">
          {item.chain.lines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
        <Link
          href={`/w/${encodeURIComponent(workspaceId)}/hierarchy`}
          className="mt-2 inline-block text-sm text-ink underline"
        >
          Resume the lead or move its reports in Hierarchy
        </Link>
      </div>
    );
  if (item.mention)
    return (
      <div
        className={cn(
          "max-w-xl rounded-2xl border bg-panel px-4 py-3",
          focused ? "border-ink" : "border-line",
        )}
      >
        <p className="text-sm font-medium">
          {item.mention.reason === "review"
            ? `${item.memberName || "A member"} on a card waiting for your review`
            : `${item.memberName || "A member"} mentioned you`}
          {" · "}
          <span className="text-ink-2">{item.title || item.card}</span>
        </p>
        <p className="mt-1 line-clamp-6 text-sm whitespace-pre-wrap text-ink-2">
          {item.mention.body}
        </p>
        <Link
          href={`/w/${encodeURIComponent(workspaceId)}/kanban?card=${encodeURIComponent(item.card)}`}
          className="mt-2 inline-block text-sm text-ink underline"
        >
          Answer on the card
        </Link>
      </div>
    );
  if (item.note)
    return (
      <div
        className={cn(
          "max-w-xl rounded-2xl border bg-panel px-4 py-3",
          focused ? "border-ink" : "border-line",
        )}
      >
        <p className="text-sm font-medium">{item.title}</p>
        {item.note.kind === "skills_improved" ? (
          <SkillsImprovedNote
            workspaceId={workspaceId}
            detail={item.note.detail}
          />
        ) : item.note.kind === "skill_request" ? (
          <SkillRequestNote
            workspaceId={workspaceId}
            detail={item.note.detail}
          />
        ) : (
          item.note.detail && (
            <p className="mt-1 text-sm whitespace-pre-wrap text-ink-2">
              {item.note.detail}
            </p>
          )
        )}
        {(item.note.kind === "recap" || item.note.kind === "weekly") && (
          <Link
            href={`/w/${encodeURIComponent(workspaceId)}/vision`}
            className="mt-2 inline-block text-sm text-ink underline"
          >
            Open the Vision page
          </Link>
        )}
      </div>
    );
  if (item.approval)
    return (
      <div
        className={cn(
          "max-w-xl rounded-2xl border bg-panel px-4 py-3",
          focused ? "border-ink" : "border-line",
        )}
      >
        <p className="text-sm">
          <span className="font-medium">{item.memberName}</span> ·{" "}
          {item.approval.title}
        </p>
        {item.approval.detail && (
          <pre className="mt-1 overflow-x-auto rounded-lg bg-sunken px-2 py-1 text-xs whitespace-pre-wrap text-ink-2">
            {item.approval.detail}
          </pre>
        )}
        <Link
          href={`/w/${encodeURIComponent(workspaceId)}/chats/${String(item.approval.chatId)}`}
          className="mt-2 inline-block text-sm text-ink underline"
        >
          Answer in the chat
        </Link>
      </div>
    );
  return (
    <BlockedCardItem
      workspaceId={workspaceId}
      item={item}
      focused={focused}
      onAnswered={onAnswered}
    />
  );
}

/** A card Hermes holds blocked for the owner (no AGOS row: a plain question in
 * the block's reason), or one whose blocker chain stalled: an answer is a
 * comment and the card goes on; a stalled one points to the Kanban. */
function BlockedCardItem({
  workspaceId,
  item,
  focused,
  onAnswered,
}: {
  workspaceId: string;
  item: InboxItem;
  focused: boolean;
  onAnswered: (label: string) => void;
}) {
  const b = item.blocked;
  const [text, setText] = useState("");
  const [busy, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const answer = () => {
    start(async () => {
      const form = new FormData();
      form.set("text", text);
      const r = await answerCard(workspaceId, item.card, { error: null }, form);
      if (r.error) setError(r.error);
      else onAnswered(item.title);
    });
  };
  return (
    <div
      className={cn(
        "max-w-xl rounded-2xl border bg-panel px-4 py-3",
        focused ? "border-ink" : "border-line",
      )}
    >
      <Eyebrow>
        {item.memberName || "A card"} · {item.title}
      </Eyebrow>
      {b && (
        <p className="mt-1 text-sm whitespace-pre-wrap">
          {b.stalled ? b.why : b.action || b.reason || b.why}
        </p>
      )}
      {b?.stalled ? (
        <p className="mt-1 text-xs text-ink-3">
          Waits on {(b.blockers ?? []).join(", ")}: unblock or finish those, or
          cancel this one, on the Kanban.
        </p>
      ) : (
        <>
          <Textarea
            className="mt-2"
            rows={2}
            value={text}
            placeholder="Your answer (a comment on the card; it goes on)"
            onChange={(e) => {
              setText(e.target.value);
            }}
          />
          <div className="mt-2 flex items-center gap-2">
            {error && <p className="mr-auto text-sm text-danger">{error}</p>}
            {!error && <span className="mr-auto" />}
            <Button
              variant="primary"
              disabled={busy || !text.trim()}
              onClick={answer}
            >
              {busy ? "Sending…" : "Answer"}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
