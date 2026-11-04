"use client";

import { useActionState, useState, useTransition } from "react";
import type { KanbanCardDetail } from "@/data/types";
import { answerKanbanAsk } from "@/features/chats/actions";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { Textarea } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { Markdown } from "@/shared/ui/markdown";
import { answerCard } from "./card-actions";

export function AskRow({
  workspaceId,
  ask,
}: {
  workspaceId: string;
  ask: NonNullable<KanbanCardDetail["asks"]>[number];
}) {
  const [busy, start] = useTransition();
  const [said, setSaid] = useState<string | null>(null);
  const decide = (allow: boolean) => {
    start(async () => {
      const res = await answerKanbanAsk(workspaceId, ask.id, allow);
      setSaid(res.error ?? res.message ?? null);
    });
  };
  return (
    <div className="border-b border-line bg-attention/30 px-5 py-3">
      <p className="text-sm">
        ⚠️ <span className="font-medium">{ask.memberName}</span> needs your OK:{" "}
        {ask.label}.
      </p>
      {ask.detail && (
        <pre className="mt-1 overflow-x-auto rounded-lg bg-panel px-2 py-1 text-xs whitespace-pre-wrap text-ink-2">
          {ask.detail}
        </pre>
      )}
      {said ? (
        <p className="mt-2 text-sm text-ink-2">{said}</p>
      ) : (
        <div className="mt-2 flex gap-2">
          <Button
            type="button"
            variant="primary"
            disabled={busy}
            onClick={() => {
              decide(true);
            }}
          >
            Allow once
          </Button>
          <Button
            type="button"
            disabled={busy}
            onClick={() => {
              decide(false);
            }}
          >
            Deny
          </Button>
        </div>
      )}
    </div>
  );
}

/** Blocked: why, and (❓) his answer, which unblocks it. */
export function Waiting({
  workspaceId,
  cardId,
  question,
  asks,
  onAnswer,
}: {
  workspaceId: string;
  cardId: string;
  question: string;
  asks: boolean;
  /** Shows the card going on at once (inside this form's action). */
  onAnswer: () => void;
}) {
  const [state, action, pending] = useActionState(
    (prev: Awaited<ReturnType<typeof answerCard>>, form: FormData) => {
      // Only an answer the action takes (it refuses a blank one) moves early.
      const text = form.get("text");
      if (typeof text === "string" && text.trim()) onAnswer();
      return answerCard(workspaceId, cardId, prev, form);
    },
    { error: null },
  );
  return (
    <div
      className={cn(
        "border-b border-line px-5 py-3",
        asks ? "bg-attention/30" : "bg-danger-soft/40",
      )}
    >
      <p className="text-sm font-medium">
        {asks ? "❓ The member asks you" : "⚠️ Blocked"}
      </p>
      {question && (
        <div className="mt-1 text-sm">
          <Markdown text={question} />
        </div>
      )}
      {asks && (
        <form action={action} className="mt-2 flex flex-col gap-2">
          <Textarea name="text" rows={2} placeholder="Your answer" required />
          <div className="flex items-center gap-2">
            <FormStatus error={state.error} className="mr-auto" />
            <Button type="submit" variant="primary" disabled={pending}>
              {pending ? "Sending…" : "Answer and go on"}
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}
