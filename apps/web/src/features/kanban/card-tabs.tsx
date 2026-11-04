"use client";

import Link from "next/link";
import { useActionState, useState } from "react";
import type { Chat, KanbanBoard, KanbanCardDetail } from "@/data/types";
import { Conversation } from "@/features/chats/conversation";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { Textarea } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { Markdown } from "@/shared/ui/markdown";
import { commentOnCard, type ThreadState } from "./board-actions";
import { eventName, when } from "./card-format";

export function DescriptionBody({
  card,
  docHref,
}: {
  card: KanbanCardDetail;
  docHref: (key: string) => string;
}) {
  const docs = card.documents ?? [];
  return (
    <div className="flex flex-col gap-5">
      {card.body ? (
        <div className="text-sm">
          <Markdown text={card.body} />
        </div>
      ) : (
        <p className="text-sm text-ink-3">No description.</p>
      )}
      {docs.length > 0 && (
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink-2">
          <span className="text-ink-3">Documents:</span>
          {docs.map((d) => (
            <Link
              key={d.key}
              href={docHref(d.key)}
              scroll={false}
              className="font-mono text-xs underline hover:text-ink"
            >
              {d.key}.md
              <span className="text-ink-3"> v{d.revision}</span>
            </Link>
          ))}
        </p>
      )}
      {card.summary && (
        <section className="rounded-xl bg-sunken px-3 py-2">
          <h3 className="text-sm font-semibold">Latest result</h3>
          <div className="mt-1 text-sm">
            <Markdown text={card.summary} />
          </div>
        </section>
      )}
      {card.events.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold">What happened</h3>
          <ol className="mt-3 flex flex-col border-l border-line pl-4">
            {card.events.map((e, i) => (
              <li key={i} className="relative pb-3 text-xs last:pb-0">
                <span
                  aria-hidden="true"
                  className="absolute top-1 -left-[1.3rem] size-2 rounded-full border border-line-strong bg-panel"
                />
                <span className="font-medium text-ink">
                  {eventName(e.kind)}
                </span>
                <span className="text-ink-3"> · {when(e.at)}</span>
                {e.detail && (
                  <span className="mt-0.5 line-clamp-1 text-ink-2">
                    {e.detail}
                  </span>
                )}
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}

export function PlanTab({ card }: { card: KanbanCardDetail }) {
  const plan = card.plan ?? [];
  if (plan.length === 0)
    return (
      <p className="text-sm text-ink-3">
        The member writes its steps here when it starts working on the card.
      </p>
    );
  return (
    <ol className="flex max-w-prose flex-col">
      {plan.map((step, i) => (
        <li key={i} className="flex gap-3 pb-4 last:pb-0">
          <span
            aria-label={step.status}
            className={cn(
              "mt-0.5 grid size-6 shrink-0 place-items-center rounded-full text-xs font-semibold",
              step.status === "completed" && "bg-accent text-accent-ink",
              step.status === "in_progress" &&
                "text-ink ring-2 ring-ink ring-offset-2 ring-offset-panel",
              (step.status === "pending" || step.status === "cancelled") &&
                "border border-dashed border-line-strong text-ink-3",
            )}
          >
            {i + 1}
          </span>
          <span
            className={cn(
              "text-sm text-ink",
              step.status === "cancelled" && "text-ink-3 line-through",
            )}
          >
            {step.text}
          </span>
        </li>
      ))}
    </ol>
  );
}

type Ref = NonNullable<KanbanCardDetail["refs"]>[number];

/** Card ids in a text, as chips (title + status) that open the card. */
function RefChips({
  text,
  refs,
  cardHref,
}: {
  text: string;
  refs: Ref[];
  cardHref: (id: string) => string;
}) {
  const named = refs.filter((r) => text.includes(r.id));
  if (named.length === 0) return null;
  return (
    <span className="mt-1 flex flex-wrap gap-1">
      {named.map((r) => (
        <Link
          key={r.id}
          href={cardHref(r.id)}
          scroll={false}
          className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-line bg-sunken px-1.5 py-0.5 text-xs text-ink-2 hover:border-ink-3"
          title={`${r.id} · ${r.statusLabel || r.status}`}
        >
          <span className="font-mono text-ink-3">{r.id}</span>
          <span className="truncate">{r.title}</span>
          <span className="text-ink-3">· {r.statusLabel || r.status}</span>
        </Link>
      ))}
    </span>
  );
}

/** What can follow the "@" or "t_" he is typing. */
function suggestions(
  word: string,
  members: KanbanBoard["members"],
  refs: Ref[],
  cardId: string,
): { insert: string; label: string }[] {
  if (word.startsWith("@")) {
    const typed = word.slice(1).toLowerCase();
    return [
      ...members
        .filter((m) => m.name !== "founder") // he is @owner here
        .map((m) => ({ insert: `@${m.name}`, label: m.title })),
      { insert: "@owner", label: "You (your Inbox)" },
    ]
      .filter(
        (s) =>
          s.insert.slice(1).toLowerCase().startsWith(typed) ||
          s.label.toLowerCase().startsWith(typed),
      )
      .slice(0, 8);
  }
  if (word.startsWith("t_"))
    return refs
      .filter((r) => r.id !== cardId && r.id.startsWith(word))
      .map((r) => ({ insert: r.id, label: r.title }))
      .slice(0, 8);
  return [];
}

export function CommentsTab({
  workspaceId,
  card,
  members,
  cardHref,
}: {
  workspaceId: string;
  card: KanbanCardDetail;
  members: KanbanBoard["members"];
  cardHref: (id: string) => string;
}) {
  const [text, setText] = useState("");
  const [caret, setCaret] = useState(0);
  const [state, comment, commenting] = useActionState(
    async (prev: ThreadState, form: FormData) => {
      const r = await commentOnCard(workspaceId, card.id, prev, form);
      if (!r.error) setText("");
      return r;
    },
    { error: null },
  );
  const refs = card.refs ?? [];
  const before = text.slice(0, caret);
  const word = /(?:^|\s)(@[\w-]*|t_[0-9a-f]*)$/.exec(before)?.[1] ?? "";
  const options = word ? suggestions(word, members, refs, card.id) : [];
  const pick = (insert: string) => {
    const start = before.length - word.length;
    setText(`${text.slice(0, start)}${insert} ${text.slice(caret)}`);
    setCaret(start + insert.length + 1);
  };
  const blocked = card.status === "blocked";
  return (
    <div className="flex max-w-prose flex-col">
      <ol className="flex flex-col gap-2">
        {card.comments.map((c, i) => (
          <li
            key={c.id ? String(c.id) : String(i)}
            className="rounded-xl border border-line px-3 py-2"
          >
            <p className="text-xs text-ink-3">
              {c.author} · {when(c.at)}
            </p>
            <div className="mt-0.5 text-sm">
              <Markdown text={c.body} />
            </div>
            <RefChips text={c.body} refs={refs} cardHref={cardHref} />
          </li>
        ))}
        {card.comments.length === 0 && (
          <li className="text-sm text-ink-3">No comments yet.</li>
        )}
      </ol>
      <form action={comment} className="mt-3 flex flex-col gap-2">
        <div className="relative">
          <Textarea
            name="text"
            rows={3}
            value={text}
            aria-label="Comment"
            placeholder={`It reaches ${card.memberTitle || "its member"} only. @name brings someone in (they follow the card, woken once); t_… links a card.`}
            onChange={(e) => {
              setText(e.currentTarget.value);
              setCaret(e.currentTarget.selectionStart);
            }}
            onSelect={(e) => {
              setCaret(e.currentTarget.selectionStart);
            }}
          />
          {options.length > 0 && (
            <ul
              aria-label="Mention"
              className="absolute bottom-full left-0 z-10 mb-1 w-64 overflow-hidden rounded-lg border border-line bg-panel text-sm shadow-lg"
            >
              {options.map((o) => (
                <li key={o.insert}>
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-sunken"
                    onClick={() => {
                      pick(o.insert);
                    }}
                  >
                    <span className="font-mono text-xs">{o.insert}</span>
                    <span className="truncate text-ink-3">{o.label}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        {blocked && card.blockKind !== "needs_input" && (
          <label className="flex items-center gap-2 text-sm text-ink-2">
            <input type="checkbox" name="resume" />
            Start it again with this comment
          </label>
        )}
        <div className="flex items-center gap-2">
          <FormStatus error={state.error} className="mr-auto" />
          <Button type="submit" disabled={commenting || !text.trim()}>
            {commenting ? "Sending…" : "Comment"}
          </Button>
        </div>
        {!state.error && (state.woke?.length ?? 0) > 0 && (
          <ul className="text-xs text-ink-2">
            {(state.woke ?? []).map((w) => (
              <li key={w.who}>
                <span className="font-medium">{w.title}</span>: {w.said}
              </li>
            ))}
          </ul>
        )}
      </form>
    </div>
  );
}

export function ChatTab({
  workspaceId,
  card,
  chat,
}: {
  workspaceId: string;
  card: KanbanCardDetail;
  chat: Chat | null;
}) {
  if (!chat)
    return (
      <p className="text-sm text-ink-3">
        {card.member === "founder"
          ? "This card is yours (the Founder's): no agent works it. Mark it done when it's done, or tell the Co-Founder."
          : "Give the card to a member first: the chat is with them."}
      </p>
    );
  return (
    <div className="-mx-5 -my-5 flex h-full min-h-[24rem] flex-col">
      <Conversation
        key={chat.id}
        workspaceId={workspaceId}
        chat={chat}
        people={{ [card.member]: card.memberTitle }}
        placeholder={`Message ${card.memberTitle} about this card…`}
      />
    </div>
  );
}
