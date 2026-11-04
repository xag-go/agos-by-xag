"use client";

import { useEffect, useState, useTransition } from "react";
import type { InboxItem } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { decideHeld, explainHeld } from "./actions";

type Held = NonNullable<InboxItem["held"]>;
type Change = Held["ops"][number];

/** A memory or skill change an agent wants and Hermes holds for the owner
 * (its write_approval queue), in plain words: what it wants, in short why
 * (Hermes's helper model), the notes as they are and as they would be, and
 * what each button does. The same request asked again is one card. */
export function HeldCard({
  workspaceId,
  held,
  focused,
  onDecided,
}: {
  workspaceId: string;
  held: Held;
  focused: boolean;
  onDecided: (words: string) => void;
}) {
  const [busy, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const asked = held.ids.length;
  const canApprove = !held.stale || held.left > 0;
  const decide = (approve: boolean) => {
    setError(null);
    start(async () => {
      const r = await decideHeld(workspaceId, held, approve);
      if (r.error) setError(r.error);
      else
        onDecided(
          approve
            ? `Approved: ${held.agent}'s change is saved.`
            : `Rejected: ${held.agent}'s ${held.subsystem === "skills" ? "skill" : "memory"} stays as it is.`,
        );
    });
  };
  return (
    <div
      className={cn(
        "flex max-w-2xl flex-col gap-3 rounded-2xl border bg-panel px-4 py-3",
        focused ? "border-ink" : "border-line",
      )}
    >
      <div className="flex flex-col gap-0.5">
        <p className="text-sm font-medium">{held.title}</p>
        <p className="text-xs text-ink-3">
          {held.origin === "background_review"
            ? "Learned after a chat"
            : "During a conversation"}
          {" · "}
          {when(held.firstAt, held.lastAt)}
          {asked > 1 ? ` · asked ${String(asked)} times` : ""}
        </p>
      </div>
      <InShort workspaceId={workspaceId} held={held} />
      {held.stale ? (
        <p className="rounded-lg border border-line px-3 py-2 text-sm text-warn">
          {canApprove
            ? "Part of this is already done: a note it wanted to remove or change is already gone. Approve saves the rest."
            : "Already done: the notes it wanted to change are gone. Reject clears it."}
        </p>
      ) : null}
      {held.ops.length > 0 ? (
        <div className="flex flex-col gap-3">
          {held.ops.map((op, n) => (
            <ChangeBlock key={`${op.action}-${String(n)}`} op={op} />
          ))}
        </div>
      ) : held.detail ? (
        <div className="flex flex-col gap-1">
          <p className="text-xs font-medium text-ink-2">The change</p>
          <pre className="max-h-80 overflow-auto rounded-lg bg-sunken p-3 text-xs whitespace-pre-wrap">
            {held.detail}
          </pre>
        </div>
      ) : null}
      <div className="flex flex-col gap-2 border-t border-line pt-3">
        <div className="flex flex-wrap items-center gap-2">
          {canApprove ? (
            <Button
              variant="primary"
              disabled={busy}
              onClick={() => {
                decide(true);
              }}
            >
              {busy ? "Working…" : "Approve"}
            </Button>
          ) : null}
          <Button
            disabled={busy}
            onClick={() => {
              decide(false);
            }}
          >
            {!canApprove && busy ? "Working…" : "Reject"}
          </Button>
        </div>
        <ul className="text-xs text-ink-2">
          {canApprove ? (
            <li>
              <span className="font-medium text-ink">Approve</span>:{" "}
              {held.subsystem === "skills"
                ? "the skill is changed as shown."
                : held.stale
                  ? "the changes not done yet are made in its memory."
                  : "the changes above are made in its memory."}
              {asked > 1
                ? " The newest version is used; the older copies are cleared."
                : ""}
            </li>
          ) : null}
          <li>
            <span className="font-medium text-ink">Reject</span>:{" "}
            {held.subsystem === "skills" ? "the skill" : "its memory"} stays as
            it is{asked > 1 ? `; all ${String(asked)} copies are cleared` : ""}.
          </li>
        </ul>
        {error ? (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        ) : null}
      </div>
    </div>
  );
}

/** "In short": one or two plain sentences from Hermes's helper model, asked
 * when the card shows (kept by the core, so asked once per request). */
function InShort({ workspaceId, held }: { workspaceId: string; held: Held }) {
  const [text, setText] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const { profile, subsystem, id } = held;
  useEffect(() => {
    let live = true;
    void explainHeld(workspaceId, { profile, subsystem, id }).then((r) => {
      if (!live) return;
      if (r.text) setText(r.text);
      else setFailed(r.error ?? "no answer");
    });
    return () => {
      live = false;
    };
  }, [workspaceId, profile, subsystem, id]);
  if (failed) return null;
  return (
    <p className="text-sm text-ink">
      <span className="font-medium">In short: </span>
      {text ?? <span className="text-ink-3">Hermes is reading it…</span>}
    </p>
  );
}

function ChangeBlock({ op }: { op: Change }) {
  const about = op.target === "user" ? " (about you)" : "";
  if (op.action === "add")
    return <Note label={`Add this note${about}`} text={op.after} />;
  if (op.action === "remove")
    return (
      <Note
        label={`Remove this note${about}`}
        text={op.before}
        gone={op.gone}
        struck
      />
    );
  return (
    <div className="flex flex-col gap-2">
      <Note
        label={`Change this note${about}`}
        text={op.before}
        gone={op.gone}
      />
      <Note label="Into" text={op.after} />
    </div>
  );
}

function Note({
  label,
  text,
  gone,
  struck,
}: {
  label: string;
  text: string;
  gone?: boolean;
  struck?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1">
      <p className="text-xs font-medium text-ink-2">
        {label}
        {gone ? " · already gone" : ""}
      </p>
      <p
        className={cn(
          "max-h-60 overflow-auto rounded-lg bg-sunken px-3 py-2 text-sm whitespace-pre-wrap",
          struck && "text-ink-2",
        )}
      >
        {text || "(empty)"}
      </p>
    </div>
  );
}

function when(first: string, last: string): string {
  const a = first ? new Date(first) : null;
  const b = last ? new Date(last) : null;
  const fmt = (d: Date) =>
    d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  if (!b || Number.isNaN(b.getTime())) return "";
  if (!a || Number.isNaN(a.getTime()) || first === last) return fmt(b);
  return `${fmt(a)} – ${fmt(b)}`;
}
