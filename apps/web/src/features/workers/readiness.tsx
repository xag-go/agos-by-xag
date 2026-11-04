"use client";

import Link from "next/link";
import { useEffect, useState, useTransition } from "react";
import type { Readiness, ReadinessItem } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { Input } from "@/shared/ui/field";
import {
  chooseReadiness,
  readinessOf,
  type ReadinessChoice,
  saveKit,
} from "./actions";
import { sentKit, type Kit, type KitState } from "./kit-types";
import { KitChip, ReadinessChip, SuggestKitButton } from "./kit-chips";
import { KitEditor } from "./kit-editor";

const ACTION_WORDS: Record<string, string> = {
  connect: "Connect",
  add_key: "Add key",
  answer: "Answer",
  make_topic: "Make topic",
};

function Mark({ item }: { item: ReadinessItem }) {
  return (
    <span
      aria-hidden
      className={cn(
        "mt-0.5 grid size-4 shrink-0 place-items-center rounded-full text-10 font-bold",
        item.state === "ready" && "bg-live text-panel",
        item.state === "not_needed" && "bg-sunken text-ink-3",
        item.state === "missing" &&
          (item.owner
            ? "bg-attention text-attention-ink"
            : "bg-sunken text-ink-2"),
      )}
    >
      {item.state === "ready" ? "✓" : item.state === "not_needed" ? "–" : "!"}
    </span>
  );
}

/** A member's Readiness: each item of its kit checked for real, with the
 * owner's buttons (Connect / Add key / Answer / Not needed / Start anyway /
 * Retry / Skip test). Loads itself unless given. */
export function ReadinessPanel({
  workspaceId,
  member,
  initial,
  kitState,
  kitCard,
}: {
  workspaceId: string;
  member: string;
  initial?: Readiness | null;
  /** Its kit (none / incomplete / whole); absent: not known here (no Suggest kit). */
  kitState?: KitState | null;
  /** The card already carrying a kit for it (the ask, or its proposal). */
  kitCard?: string | null;
}) {
  const [view, setView] = useState<Readiness | null | undefined>(initial);
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  const [kit, setKit] = useState<Kit | null>(null);
  const [why, setWhy] = useState<{ item: string; text: string } | null>(null);

  useEffect(() => {
    if (initial !== undefined) return;
    let gone = false;
    void readinessOf(workspaceId, member).then((r) => {
      if (gone) return;
      if (r.error) setError(r.error);
      else setView(r.readiness ?? null);
    });
    return () => {
      gone = true;
    };
  }, [workspaceId, member, initial]);

  const act = (choice: ReadinessChoice, item = "", reason = "") => {
    start(async () => {
      setError(null);
      const r = await chooseReadiness(
        workspaceId,
        member,
        choice,
        item,
        reason,
      );
      if (r.error) setError(r.error);
      else setView(r.readiness ?? null);
    });
  };
  const look = () => {
    start(async () => {
      setError(null);
      const r = await readinessOf(workspaceId, member, true);
      if (r.error) setError(r.error);
      else setView(r.readiness ?? null);
    });
  };

  if (view === undefined) {
    return <p className="text-sm text-ink-3">Checking…</p>;
  }
  if (view === null || kit !== null) {
    return (
      <div className="flex flex-col gap-3">
        {kit === null ? (
          <>
            <p className="text-sm text-ink-2">
              No kit yet: it was hired before kits. The Co-Founder can suggest
              one from its role and its work (it arrives in your Inbox to edit
              and approve), or give it one yourself: the tools, skills and files
              it needs, and a first test. AGOS then checks each one for real.
            </p>
            <div className="flex flex-wrap items-start gap-2">
              {kitState !== undefined && (
                <SuggestKitButton
                  workspaceId={workspaceId}
                  member={member}
                  card={kitCard}
                />
              )}
              <Button
                variant={kitState !== undefined ? "ghost" : "secondary"}
                className="self-start"
                onClick={() => {
                  setKit({ onboarding: { task: "", criteria: [] } });
                }}
              >
                Add a kit
              </Button>
            </div>
          </>
        ) : (
          <>
            <KitEditor kit={kit} onChange={setKit} />
            <div className="flex items-center gap-2">
              <Button
                variant="primary"
                disabled={busy}
                onClick={() => {
                  start(async () => {
                    setError(null);
                    const r = await saveKit(
                      workspaceId,
                      member,
                      sentKit(kit) as Record<string, unknown>,
                    );
                    if (r.error) setError(r.error);
                    else {
                      setView(r.readiness ?? null);
                      setKit(null);
                    }
                  });
                }}
              >
                {busy ? "Saving…" : "Save the kit"}
              </Button>
              <Button
                variant="ghost"
                onClick={() => {
                  setKit(null);
                }}
              >
                Cancel
              </Button>
            </div>
          </>
        )}
        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
      </div>
    );
  }

  const test = view.onboarding;
  const last = test?.tries.at(-1);
  const graded = test?.tries.filter((t) => t.grade).at(-1);
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <ReadinessChip state={view.state} />
        <p className="text-sm text-ink-2">
          {view.state === "ready"
            ? view.startedAnyway
              ? "Started anyway: it takes work now."
              : "Ready: it takes work now."
            : view.state === "onboarding"
              ? "Everything is there: it is taking its first test."
              : "It gets no work until each item below is there."}
        </p>
      </div>
      {kitState === "incomplete" && (
        <div className="flex flex-col gap-2 rounded-xl border border-line px-3 py-2">
          <p className="flex items-center gap-2 text-sm text-ink-2">
            <KitChip state="incomplete" />
            Its kit misses a part (tools, docs, a first test or a library
            skill).
          </p>
          <SuggestKitButton
            workspaceId={workspaceId}
            member={member}
            card={kitCard}
          />
        </div>
      )}
      <ul className="flex flex-col divide-y divide-line rounded-xl border border-line">
        {view.items.map((i) => (
          <li key={i.id} className="flex flex-col gap-1 px-3 py-2">
            <div className="flex items-start gap-2">
              <Mark item={i} />
              <div className="min-w-0 flex-1">
                <p
                  className={cn(
                    "text-sm",
                    i.state === "not_needed"
                      ? "text-ink-3 line-through"
                      : "text-ink",
                  )}
                >
                  {i.label}
                </p>
                {i.how && <p className="text-xs text-ink-3">{i.how}</p>}
                {i.state === "not_needed" && i.reason && (
                  <p className="text-xs text-ink-3">Not needed: {i.reason}</p>
                )}
                {i.route?.text && (
                  <p className="text-xs text-ink-2">
                    Co-Founder: {i.route.text}
                  </p>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {i.state === "missing" &&
                  i.href &&
                  ACTION_WORDS[i.action] &&
                  i.action !== "make_topic" && (
                    <Link
                      href={i.href}
                      className="rounded-lg px-2 py-1 text-xs font-medium text-ink underline decoration-line underline-offset-2 hover:decoration-ink"
                    >
                      {ACTION_WORDS[i.action]}
                    </Link>
                  )}
                {i.state === "missing" && i.action === "make_topic" && (
                  <Button
                    className="h-7 px-2 text-xs"
                    disabled={busy}
                    onClick={() => {
                      act("make_topic", i.id);
                    }}
                  >
                    Make topic
                  </Button>
                )}
                {i.state === "missing" && (
                  <Button
                    variant="ghost"
                    className="h-7 px-2 text-xs"
                    disabled={busy}
                    onClick={() => {
                      setWhy({ item: i.id, text: "" });
                    }}
                  >
                    Not needed
                  </Button>
                )}
                {i.state === "not_needed" && (
                  <Button
                    variant="ghost"
                    className="h-7 px-2 text-xs"
                    disabled={busy}
                    onClick={() => {
                      act("clear", i.id);
                    }}
                  >
                    Undo
                  </Button>
                )}
              </div>
            </div>
            {why?.item === i.id && (
              <form
                className="flex items-center gap-1.5 pl-6"
                onSubmit={(e) => {
                  e.preventDefault();
                  act("not_needed", i.id, why.text);
                  setWhy(null);
                }}
              >
                <Input
                  autoFocus
                  aria-label="Why it isn't needed"
                  value={why.text}
                  placeholder="Why (optional)"
                  onChange={(e) => {
                    setWhy({ item: i.id, text: e.target.value });
                  }}
                />
                <Button type="submit" className="h-9" disabled={busy}>
                  Save
                </Button>
              </form>
            )}
          </li>
        ))}
      </ul>
      {test && (
        <div className="flex flex-col gap-1 rounded-xl border border-line px-3 py-2 text-sm">
          <p className="font-medium text-ink">First test</p>
          <p className="whitespace-pre-wrap text-ink-2">{test.task}</p>
          <p className="text-xs text-ink-3 tabular-nums">
            {test.skipped
              ? "Skipped by you."
              : test.passed
                ? "Passed."
                : last
                  ? `Try ${String(last.n)}: ${last.grade ?? (last.status === "done" ? "being graded" : "running")}${test.escalated ? " — failed every try, your call" : ""}`
                  : "Starts once every item is there."}
          </p>
          {graded?.notes && (
            <p className="text-xs text-ink-2">
              Grader on try {String(graded.n)} ({graded.grade}): {graded.notes}
            </p>
          )}
        </div>
      )}
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button disabled={busy} onClick={look}>
          {busy ? "Checking…" : "Check again"}
        </Button>
        {test?.escalated && (
          <Button
            disabled={busy}
            onClick={() => {
              act("retry");
            }}
          >
            Retry test
          </Button>
        )}
        {test && !test.passed && !test.skipped && view.state !== "ready" && (
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() => {
              act("skip_test");
            }}
          >
            Skip test
          </Button>
        )}
        {view.state !== "ready" && (
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() => {
              act("start_anyway");
            }}
          >
            Start anyway
          </Button>
        )}
        {view.startedAnyway && (
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() => {
              act("clear", "member");
            }}
          >
            Undo start anyway
          </Button>
        )}
        {view.gapCard && (
          <Link
            href={`/w/${encodeURIComponent(workspaceId)}/kanban?card=${encodeURIComponent(view.gapCard)}`}
            className="ml-auto text-xs text-ink-3 underline decoration-line underline-offset-2 hover:decoration-ink"
          >
            The Co-Founder&apos;s card
          </Link>
        )}
      </div>
    </div>
  );
}
