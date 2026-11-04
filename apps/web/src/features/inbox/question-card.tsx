"use client";

import { useState, useTransition } from "react";
import type { Question } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { Textarea } from "@/shared/ui/field";
import { answerQuestion } from "./actions";
import { Eyebrow } from "@/shared/ui/eyebrow";
import { AttentionBadge } from "@/shared/ui/attention-badge";

type Option = { id: string; label: string };
type Task = { title: string; body?: string; member?: string };
type Payload = {
  question?: string;
  placeholder?: string;
  options?: Option[];
  items?: Option[];
  tasks?: Task[];
};

const KIND_LABEL: Record<Question["kind"], string> = {
  ask: "Question",
  confirm: "Yes or no",
  choice: "Pick one",
  checkbox: "Pick any",
  verdicts: "Approve or reject each",
  suggest_tasks: "Suggested tasks",
};

/**
 * One typed question from an agent, with the control its kind needs: a text
 * box, Yes / No, one choice, checkboxes, a verdict per item, or the suggested
 * tasks to accept one by one. The answer goes on the Hermes card and the card
 * goes on; the core refuses a second, different answer.
 */
export function QuestionCard({
  workspaceId,
  question: q,
  onAnswered,
  focused = false,
}: {
  workspaceId: string;
  question: Question;
  onAnswered?: (id: number, label: string) => void;
  focused?: boolean;
}) {
  const payload = q.payload as Payload;
  const [busy, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [text, setText] = useState("");
  const [picked, setPicked] = useState<Set<string>>(() => new Set());
  const [verdicts, setVerdicts] = useState<
    Record<string, "approve" | "reject">
  >({});
  const [accepted, setAccepted] = useState<Set<number>>(() => new Set());

  const send = (answer: Record<string, unknown>) =>
    start(async () => {
      const r = await answerQuestion(workspaceId, q.id, {
        ...answer,
        ...(note.trim() ? { note: note.trim() } : {}),
      });
      if (r.error) {
        setError(r.error);
        return;
      }
      onAnswered?.(q.id, q.label);
    });

  const options = payload.options ?? [];
  const items = payload.items ?? [];
  const tasks = payload.tasks ?? [];
  const allJudged = items.length > 0 && items.every((i) => verdicts[i.id]);

  return (
    <div
      className={cn(
        "max-w-xl rounded-2xl border bg-panel px-4 py-3",
        focused ? "border-ink" : "border-line",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Eyebrow>
            ❓ {q.memberName} asks · {KIND_LABEL[q.kind]} · card {q.card}
          </Eyebrow>
          <p className="mt-1 text-sm whitespace-pre-wrap">
            {payload.question || q.label}
          </p>
        </div>
        <AttentionBadge shrink>Waiting for you</AttentionBadge>
      </div>

      {q.kind === "ask" && (
        <Textarea
          className="mt-2"
          rows={2}
          value={text}
          placeholder={payload.placeholder || "Your answer"}
          onChange={(e) => {
            setText(e.target.value);
          }}
        />
      )}

      {(q.kind === "choice" || q.kind === "checkbox") && (
        <ul className="mt-2 flex flex-col gap-1">
          {options.map((o) => (
            <li key={o.id}>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type={q.kind === "choice" ? "radio" : "checkbox"}
                  name={`q-${q.id}`}
                  checked={picked.has(o.id)}
                  onChange={() => {
                    setPicked((was) => {
                      if (q.kind === "choice") return new Set([o.id]);
                      const next = new Set(was);
                      if (next.has(o.id)) next.delete(o.id);
                      else next.add(o.id);
                      return next;
                    });
                  }}
                />
                {o.label}
              </label>
            </li>
          ))}
        </ul>
      )}

      {q.kind === "verdicts" && (
        <ul className="mt-2 flex flex-col gap-1.5">
          {items.map((i) => (
            <li
              key={i.id}
              className="flex items-center justify-between gap-3 text-sm"
            >
              <span className="min-w-0 truncate">{i.label}</span>
              <span className="flex shrink-0 gap-1">
                {(["approve", "reject"] as const).map((v) => (
                  <Button
                    key={v}
                    type="button"
                    variant={verdicts[i.id] === v ? "primary" : "ghost"}
                    className="h-7 px-2 text-xs"
                    onClick={() => {
                      setVerdicts((was) => ({ ...was, [i.id]: v }));
                    }}
                  >
                    {v === "approve" ? "Approve" : "Reject"}
                  </Button>
                ))}
              </span>
            </li>
          ))}
        </ul>
      )}

      {q.kind === "suggest_tasks" && (
        <ul className="mt-2 flex flex-col gap-1.5">
          {tasks.map((t, i) => (
            <li key={i} className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-1"
                checked={accepted.has(i)}
                onChange={() => {
                  setAccepted((was) => {
                    const next = new Set(was);
                    if (next.has(i)) next.delete(i);
                    else next.add(i);
                    return next;
                  });
                }}
              />
              <span className="min-w-0">
                <span className="font-medium">{t.title}</span>
                {t.member && <span className="text-ink-3"> · @{t.member}</span>}
                {t.body && (
                  <span className="block text-xs whitespace-pre-wrap text-ink-2">
                    {t.body}
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}

      {q.kind !== "ask" && (
        <Textarea
          className="mt-2"
          rows={1}
          value={note}
          placeholder="A note for the agent (optional)"
          onChange={(e) => {
            setNote(e.target.value);
          }}
        />
      )}

      <div className="mt-3 flex items-center gap-2">
        {error && <p className="mr-auto text-sm text-danger">{error}</p>}
        {!error && <span className="mr-auto" />}
        {q.kind === "confirm" ? (
          <>
            <Button
              type="button"
              variant="primary"
              disabled={busy}
              onClick={() => {
                send({ yes: true });
              }}
            >
              Yes
            </Button>
            <Button
              type="button"
              disabled={busy}
              onClick={() => {
                send({ yes: false });
              }}
            >
              No
            </Button>
          </>
        ) : (
          <Button
            type="button"
            variant="primary"
            disabled={
              busy ||
              (q.kind === "ask" && !text.trim()) ||
              (q.kind === "choice" && picked.size !== 1) ||
              (q.kind === "verdicts" && !allJudged)
            }
            onClick={() => {
              if (q.kind === "ask") send({ text: text.trim() });
              else if (q.kind === "choice") send({ selected: [...picked][0] });
              else if (q.kind === "checkbox") send({ selected: [...picked] });
              else if (q.kind === "verdicts") send({ verdicts });
              else send({ accepted: [...accepted].sort((a, b) => a - b) });
            }}
          >
            {busy
              ? "Sending…"
              : q.kind === "suggest_tasks"
                ? `Accept ${accepted.size} of ${tasks.length}`
                : "Answer"}
          </Button>
        )}
      </div>
    </div>
  );
}
