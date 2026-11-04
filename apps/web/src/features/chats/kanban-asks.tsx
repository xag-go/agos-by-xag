"use client";

import { useActionState, useState, useTransition } from "react";
import type { LiveView } from "@/data/types";
import { answerCard } from "@/features/kanban/card-actions";
import { Button } from "@/shared/ui/button";
import { Textarea } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { answerCardTokens, answerKanbanAsk } from "./actions";
import { Eyebrow } from "@/shared/ui/eyebrow";
import { AttentionBadge } from "@/shared/ui/attention-badge";
import { Panel } from "@/shared/ui/panel";

type Ask = NonNullable<LiveView["asks"]>[number];
type Question = NonNullable<LiveView["questions"]>[number];
type TokenWarning = NonNullable<LiveView["tokens"]>[number];

/**
 * A team member working a Kanban card needs the owner's OK (his "Ask me"
 * Autonomy rule). The card waits until he answers; also on his phone.
 */
export function KanbanAsks({
  workspaceId,
  asks,
  questions = [],
  tokens = [],
}: {
  workspaceId: string;
  asks: Ask[];
  questions?: Question[];
  tokens?: TokenWarning[];
}) {
  if (asks.length === 0 && questions.length === 0 && tokens.length === 0)
    return null;
  return (
    <div className="flex max-h-[45dvh] flex-col gap-2 overflow-y-auto px-4 pb-2">
      {questions.map((q) => (
        <QuestionCard key={q.card} workspaceId={workspaceId} question={q} />
      ))}
      {asks.map((a) => (
        <KanbanAskCard key={a.id} workspaceId={workspaceId} ask={a} />
      ))}
      {tokens.map((t) => (
        <TokenCard key={t.card} workspaceId={workspaceId} warning={t} />
      ))}
    </div>
  );
}

/** A card waiting for his answer (❓): answered here, the card goes on. */
export function QuestionCard({
  workspaceId,
  question: q,
}: {
  workspaceId: string;
  question: Question;
}) {
  const [state, action, pending] = useActionState(
    answerCard.bind(null, workspaceId, q.card),
    { error: null },
  );
  return (
    <Panel className="max-w-xl px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <Eyebrow>
          ❓ {q.memberTitle || "A member"} asks you · {q.title}
        </Eyebrow>
      </div>
      <p className="mt-1.5 text-sm whitespace-pre-wrap">{q.question}</p>
      {state.saved ? (
        <p className="mt-2 text-sm text-ink-2">Sent: the card goes on.</p>
      ) : (
        <form action={action} className="mt-2 flex flex-col gap-2">
          <Textarea name="text" rows={2} placeholder="Your answer" required />
          <div className="flex items-center gap-2">
            <FormStatus error={state.error} className="mr-auto" />
            <Button type="submit" variant="primary" disabled={pending}>
              {pending ? "Sending…" : "Answer"}
            </Button>
          </div>
        </form>
      )}
    </Panel>
  );
}

export function KanbanAskCard({
  workspaceId,
  ask,
  onAnswered,
}: {
  workspaceId: string;
  ask: Ask;
  /** The Inbox drops the card the moment he answers (optimistic). */
  onAnswered?: (id: number) => void;
}) {
  const [busy, start] = useTransition();
  const [said, setSaid] = useState<string | null>(null);
  const decide = (allow: boolean) =>
    start(async () => {
      const res = await answerKanbanAsk(workspaceId, ask.id, allow);
      setSaid(res.error ?? res.message ?? null);
      if (!res.error) onAnswered?.(ask.id);
    });
  return (
    <Panel className="max-w-xl px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <Eyebrow>⚠️ Needs you · card {ask.card}</Eyebrow>
        <AttentionBadge>Waiting for you</AttentionBadge>
      </div>
      <p className="mt-1.5 text-sm">
        <span className="font-medium">{ask.memberName}</span> needs your OK:{" "}
        {ask.label}.
      </p>
      {ask.detail && (
        <pre className="mt-1 overflow-x-auto rounded-lg bg-sunken px-2 py-1 text-xs whitespace-pre-wrap text-ink-2">
          {ask.detail}
        </pre>
      )}
      {said ? (
        <p className="mt-2 text-sm text-ink-2">{said}</p>
      ) : (
        <div className="mt-3 flex items-center gap-2">
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
    </Panel>
  );
}

/** A card using far more tokens than usual: it keeps going until he says. */
function TokenCard({
  workspaceId,
  warning: w,
}: {
  workspaceId: string;
  warning: TokenWarning;
}) {
  const [busy, start] = useTransition();
  const [said, setSaid] = useState<string | null>(null);
  const decide = (go: boolean) =>
    start(async () => {
      const res = await answerCardTokens(workspaceId, w.card, go);
      setSaid(res.error ?? res.message ?? null);
    });
  return (
    <Panel className="max-w-xl px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <Eyebrow>⚠️ Tokens · card {w.card}</Eyebrow>
        <AttentionBadge>Still working</AttentionBadge>
      </div>
      <p className="mt-1.5 text-sm">
        <span className="font-medium">{w.title}</span> has used {w.used} tokens,
        far more than usual.
      </p>
      {said ? (
        <p className="mt-2 text-sm text-ink-2">{said}</p>
      ) : (
        <div className="mt-3 flex items-center gap-2">
          <Button
            type="button"
            variant="primary"
            disabled={busy}
            onClick={() => {
              decide(true);
            }}
          >
            Let it go on
          </Button>
          <Button
            type="button"
            disabled={busy}
            onClick={() => {
              decide(false);
            }}
          >
            Stop it
          </Button>
        </div>
      )}
    </Panel>
  );
}
