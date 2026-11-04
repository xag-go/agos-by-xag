"use client";

import { useState, useTransition } from "react";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { Textarea } from "@/shared/ui/field";
import { voteOn, type VoteKind } from "./actions";

/**
 * 👍 / 👎 on one item (an agent's reply, a document revision). The vote shows
 * at once; a 👎 opens a small optional note. Each is said to the workspace's
 * agent through its learning conversation; a second click on the same vote takes
 * it back.
 */
export function VoteButtons({
  workspaceId,
  kind,
  target,
  vote,
  subject,
  fade = false,
}: {
  workspaceId: string;
  kind: VoteKind;
  /** reply: "<chat id>:<message id>"; revision: "<card>:<key>:<n>". */
  target: string;
  /** The vote as the page read it: 1, -1 or 0. */
  vote: number;
  /** What the item is, in words (the agent reads it with the vote). */
  subject: string;
  /** In a chat: shown on hover of the reply (group/reply) until a vote is set. */
  fade?: boolean;
}) {
  const [busy, start] = useTransition();
  const [shown, setShown] = useState(vote);
  const [noting, setNoting] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const send = (value: -1 | 0 | 1, words = "") => {
    setShown(value);
    setNoting(false);
    start(async () => {
      const r = await voteOn(workspaceId, kind, target, value, words, subject);
      if (r.error) {
        setError(r.error);
        setShown(vote);
      } else setError(null);
    });
  };
  const button = (value: 1 | -1, label: string, glyph: string) => (
    <button
      type="button"
      aria-label={label}
      aria-pressed={shown === value}
      title={label}
      disabled={busy}
      onClick={() => {
        if (shown === value) send(0);
        else if (value === -1) {
          setShown(-1);
          setNoting(true);
        } else send(1);
      }}
      className={cn(
        "rounded-md px-1.5 text-xs leading-5 text-ink-3 hover:bg-sunken hover:text-ink",
        shown === value && "bg-sunken text-ink",
      )}
    >
      {glyph}
    </button>
  );
  return (
    <span
      className={cn(
        "inline-flex flex-col gap-1",
        fade &&
          "transition-opacity group-hover/reply:opacity-100 focus-within:opacity-100",
        fade && shown === 0 && !noting && "opacity-0",
      )}
    >
      <span className="inline-flex items-center gap-0.5">
        {button(1, "Helpful", "👍")}
        {button(-1, "Needs work", "👎")}
        {error && <span className="ml-1 text-xs text-danger">{error}</span>}
      </span>
      {noting && (
        <form
          className="flex w-72 flex-col gap-1.5 rounded-xl border border-line bg-panel p-2 shadow-sm"
          onSubmit={(e) => {
            e.preventDefault();
            send(-1, note.trim());
            setNote("");
          }}
        >
          <Textarea
            rows={2}
            autoFocus
            aria-label="What needs work?"
            placeholder="What needs work? (optional)"
            value={note}
            onChange={(e) => {
              setNote(e.currentTarget.value);
            }}
          />
          <span className="flex justify-end gap-1.5">
            <Button
              type="button"
              variant="ghost"
              className="h-7 px-2 text-xs"
              onClick={() => {
                send(-1);
              }}
            >
              Skip
            </Button>
            <Button
              type="submit"
              variant="primary"
              className="h-7 px-2 text-xs"
            >
              Send
            </Button>
          </span>
        </form>
      )}
    </span>
  );
}
