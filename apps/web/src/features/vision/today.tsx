"use client";

import Link from "next/link";
import { useState } from "react";
import type { PlanNode, VisionView } from "@/data/types";
import { decideProposal } from "@/features/inbox/actions";
import { Button, ButtonLink } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { Textarea } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { tickToday } from "./actions";
import { initials, weekday, type Found } from "./format";
import { useRun } from "./use-run";
import { plural } from "@/shared/format";

type Today = VisionView["today"];
type Item = NonNullable<Today["you"]>[number];
type Card = NonNullable<Today["members"]>[number]["cards"][number];
type RhythmJob = NonNullable<VisionView["rhythm"]>[number];

/** Hermes's statuses on the team's four steps (blocked: off the line). */
const STEPS = ["To do", "Running", "Review", "Done"] as const;
function stepOf(status: string): number | "blocked" {
  if (status === "blocked") return "blocked";
  if (status === "running") return 1;
  if (status === "review") return 2;
  if (status === "done") return 3;
  return 0; // todo, ready, triage, scheduled and anything new
}

/** Each step's tone: the member's tile and the status pill. */
const TONE: Record<string, string> = {
  "0": "bg-sunken text-ink-3",
  "1": "bg-run-soft text-run-ink",
  "2": "bg-review-soft text-review-ink",
  "3": "bg-success-soft text-success",
  blocked: "bg-danger-soft text-danger",
};

/** An owner's item that asks him to look at something: Review, else Start. */
function isReview(item: Item): boolean {
  return (
    item.status === "review" ||
    item.status === "blocked" ||
    /^(review|approve|check)\b/i.test(item.title.trim())
  );
}

/**
 * Today (V3): one card. Its dark top half is the owner's part (the next item
 * big with Start, the goal it moves, then the rest); its light bottom half is
 * the team's cards of today's plan on To do → Running → Review → Done.
 */
export function TodaySection({
  workspaceId,
  today,
  rhythm,
  index,
  goals,
}: {
  workspaceId: string;
  today: Today;
  rhythm: RhythmJob[];
  index: Map<number, Found>;
  goals: PlanNode[];
}) {
  const cards = (today.members ?? []).flatMap((m) =>
    m.cards.map((c) => ({ card: c, member: m.member, role: m.title })),
  );
  const recap = rhythm.find((j) => j.which === "recap" && j.on);
  const meta = [weekday(today.date), recap ? `recap at ${recap.time}` : ""]
    .filter(Boolean)
    .join(" · ");
  return (
    <section className="flex flex-col gap-3" aria-labelledby="today-head">
      <div className="flex min-h-9 flex-wrap items-baseline gap-x-2.5 gap-y-1">
        <h2
          id="today-head"
          className="text-17 font-semibold tracking-title text-ink"
        >
          Today
        </h2>
        <span className="text-12.5 text-ink-3">{meta}</span>
      </div>
      <div className="overflow-hidden rounded-20 bg-panel shadow-lane">
        <OwnerHalf
          workspaceId={workspaceId}
          today={today}
          rhythm={rhythm}
          index={index}
          goals={goals}
        />
        <TeamHalf workspaceId={workspaceId} cards={cards} />
      </div>
    </section>
  );
}

const laneLink =
  "inline-flex min-h-9 items-center rounded-lg px-2 text-12.5 font-semibold text-lane-accent transition-colors hover:bg-white/5 hover:text-lane-ink disabled:opacity-60";

/** The goal's tone dot (its order among the goals: teal, amber, indigo). */
function toneOf(goals: PlanNode[], goal: PlanNode): string {
  const at = goals.findIndex((g) => g.id === goal.id);
  return `var(--goal-hue-${String(Math.max(0, at) % 3)})`;
}

function OwnerHalf({
  workspaceId,
  today,
  rhythm,
  index,
  goals,
}: {
  workspaceId: string;
  today: Today;
  rhythm: RhythmJob[];
  index: Map<number, Found>;
  goals: PlanNode[];
}) {
  const [busy, error, run] = useRun();
  const you = today.you ?? [];
  const plan = today.plan ?? null;
  // His Founder tasks still waiting on other cards can't be done yet (canFinish).
  const next = you.find((i) => !i.done && i.canFinish !== false) ?? null;
  const rest = you.filter((i) => i !== next);
  const done = you.filter((i) => i.done).length;
  const board = `/w/${encodeURIComponent(workspaceId)}/kanban`;
  const cardHref = (id: string) => `${board}?card=${encodeURIComponent(id)}`;
  const tick = (id: string) => {
    run(() => tickToday(workspaceId, id));
  };
  const found = next?.goalId ? index.get(next.goalId) : undefined;
  const goal = found?.goal ?? null;
  return (
    <section
      aria-label="Your part"
      className="bg-lane px-5 py-5 text-lane-ink sm:px-[22px]"
    >
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-11 font-bold tracking-caps text-lane-accent uppercase">
          Your part
        </h3>
        {you.length > 0 && (
          <span className="text-xs text-lane-ink-2 tabular-nums">
            {done} of {you.length} done
          </span>
        )}
      </div>

      {next ? (
        <div className="mt-3">
          <div className="flex items-center justify-between gap-3">
            <p className="text-11.5 font-semibold text-lane-ink-2">
              Next for you
            </p>
            <button
              type="button"
              className={cn(laneLink, "-my-2 -mr-2")}
              disabled={busy}
              aria-label={`Mark “${next.title}” done`}
              onClick={() => {
                tick(next.id);
              }}
            >
              Mark done
            </button>
          </div>
          <p className="mt-0.5 mb-3 text-19 leading-compact font-semibold tracking-heading text-balance text-white">
            {next.title}
          </p>
          <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
            <ButtonLink
              variant="primary"
              href={cardHref(next.id)}
              className="!h-10 gap-1.5 !rounded-10 !px-4 !text-13 font-semibold transition-[scale] active:scale-[0.96]"
            >
              {isReview(next) ? null : (
                <svg
                  aria-hidden
                  viewBox="0 0 12 12"
                  className="size-[11px]"
                  fill="currentColor"
                >
                  <path d="M3.5 2.2v7.6L9.8 6z" />
                </svg>
              )}
              {isReview(next) ? "Review" : "Start"}
            </ButtonLink>
            {goal && (
              <p className="flex min-w-0 flex-1 basis-40 items-center gap-[7px] text-xs text-lane-ink-2">
                <span
                  aria-hidden
                  className="size-[7px] shrink-0 rounded-full"
                  style={{ background: toneOf(goals, goal) }}
                />
                <span className="min-w-0 truncate">
                  Moves goal:{" "}
                  <b className="font-semibold text-lane-ink">{goal.title}</b>
                </span>
              </p>
            )}
          </div>
        </div>
      ) : (
        <LaneEmpty
          workspaceId={workspaceId}
          plan={plan}
          allDone={you.length > 0}
          planTime={rhythm.find((j) => j.which === "daily")}
        />
      )}

      {rest.length > 0 && (
        <ul className="mt-3.5 border-t border-white/8 pt-1.5">
          {rest.map((item) => (
            <li
              key={item.id}
              className="-ml-3 grid min-h-11 grid-cols-[40px_minmax(0,1fr)_auto] items-center gap-1"
            >
              <button
                type="button"
                className="grid size-10 place-items-center rounded-lg disabled:cursor-default"
                aria-label={
                  item.done
                    ? `${item.title}: done`
                    : `Mark “${item.title}” done`
                }
                aria-pressed={Boolean(item.done)}
                disabled={
                  busy || Boolean(item.done) || item.canFinish === false
                }
                onClick={() => {
                  tick(item.id);
                }}
              >
                <span
                  aria-hidden
                  className={cn(
                    "grid size-[18px] place-items-center rounded-5 text-10 font-bold",
                    item.done ? "bg-lane-bar text-lane" : "shadow-inset-lane",
                  )}
                >
                  {item.done ? "✓" : ""}
                </span>
              </button>
              <p
                className={cn(
                  "min-w-0 truncate text-12.5 text-lane-ink-2",
                  item.done && "line-through decoration-white/30",
                )}
              >
                {next && !item.done ? "Then: " : "Done: "}
                <b
                  className={cn(
                    "font-semibold",
                    item.done ? "text-lane-ink-2" : "text-lane-ink",
                  )}
                >
                  {item.title}
                </b>
              </p>
              {!item.done && (
                <Link className={laneLink} href={cardHref(item.id)}>
                  {isReview(item) ? "Review" : "Start"}
                </Link>
              )}
            </li>
          ))}
        </ul>
      )}
      <FormStatus error={error} />
    </section>
  );
}

function LaneEmpty({
  workspaceId,
  plan,
  allDone,
  planTime,
}: {
  workspaceId: string;
  plan: Today["plan"];
  allDone: boolean;
  planTime: RhythmJob | undefined;
}) {
  const [busy, error, run] = useRun();
  const [changing, setChanging] = useState(false);
  const [note, setNote] = useState("");
  const inbox = `/w/${encodeURIComponent(workspaceId)}/inbox`;
  const box = "mt-3 flex flex-col gap-1.5";
  const big =
    "text-19 leading-compact font-semibold tracking-heading text-balance";
  const small = "text-12.5 text-pretty text-lane-ink-2";
  if (plan?.status === "waiting")
    return (
      <div className={box}>
        <p className="text-xs font-semibold text-lane-accent">
          Today&apos;s plan is waiting for you
        </p>
        {plan.summary && <p className={big}>{plan.summary}</p>}
        <p className={small}>
          Its items are in your{" "}
          <Link className="underline underline-offset-2" href={inbox}>
            Inbox
          </Link>
          , where you can edit them before accepting.
        </p>
        {changing ? (
          <form
            className="mt-1 flex flex-col gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              run(() =>
                decideProposal(workspaceId, plan.askId, "revise", note),
              );
            }}
          >
            <Textarea
              rows={2}
              value={note}
              placeholder="What should change?"
              aria-label="What should change?"
              autoFocus
              onChange={(e) => {
                setNote(e.target.value);
              }}
            />
            <div className="flex gap-2">
              <Button
                type="submit"
                variant="primary"
                disabled={busy || !note.trim()}
              >
                Send back
              </Button>
              <Button
                className="bg-transparent text-lane-ink hover:bg-white/10"
                variant="ghost"
                disabled={busy}
                onClick={() => {
                  setChanging(false);
                }}
              >
                Cancel
              </Button>
            </div>
          </form>
        ) : (
          <div className="mt-1 flex flex-wrap items-center gap-1">
            <Button
              variant="primary"
              className="!h-10 !rounded-10 !px-5 font-semibold transition-[scale] active:scale-[0.96]"
              disabled={busy}
              onClick={() => {
                run(() => decideProposal(workspaceId, plan.askId, "approve"));
              }}
            >
              Accept
            </Button>
            <button
              type="button"
              className={laneLink}
              disabled={busy}
              onClick={() => {
                setChanging(true);
              }}
            >
              Change
            </button>
            <button
              type="button"
              className={laneLink}
              disabled={busy}
              onClick={() => {
                run(() => decideProposal(workspaceId, plan.askId, "reject"));
              }}
            >
              Skip
            </button>
          </div>
        )}
        <FormStatus error={error} />
      </div>
    );
  if (!plan || plan.status === "revised")
    return (
      <div className={box}>
        <p className={big}>
          {plan
            ? "The Co-Founder is proposing the plan again"
            : "No plan yet today"}
        </p>
        <p className={small}>
          {planTime?.on
            ? `The Co-Founder proposes today's plan at ${planTime.time}, in your Inbox.`
            : "The Co-Founder's daily plan is off: turn it on in its rhythm above."}
        </p>
      </div>
    );
  return (
    <div className={box}>
      <p className={big}>
        {allDone ? "All done for today" : "Nothing for you today"}
      </p>
      <p className={small}>
        {plan.status === "rejected"
          ? "You skipped today's plan."
          : allDone
            ? "Every item of your part is done."
            : "Today's plan has no item for you: the team works it."}
      </p>
    </div>
  );
}

function TeamHalf({
  workspaceId,
  cards,
}: {
  workspaceId: string;
  cards: { card: Card; member: string; role: string }[];
}) {
  const done = cards.filter((c) => c.card.status === "done").length;
  const board = `/w/${encodeURIComponent(workspaceId)}/kanban`;
  return (
    <section aria-label="Team" className="px-5 pt-4 pb-3.5 sm:px-[22px]">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-11 font-bold tracking-caps text-ink-3 uppercase">
          Team
        </h3>
        {cards.length > 0 && (
          <span className="text-xs text-ink-3 tabular-nums">
            {plural(cards.length, "card")} · {done} done
          </span>
        )}
      </div>
      {cards.length === 0 ? (
        <p className="pt-2 pb-1.5 text-13 text-pretty text-ink-3">
          No team cards yet
        </p>
      ) : (
        <ul className="mt-1">
          {cards.map(({ card, member, role }) => {
            const step = stepOf(card.status);
            return (
              <li
                key={card.id}
                className="border-t border-line first:border-t-0"
              >
                <Link
                  href={`${board}?card=${encodeURIComponent(card.id)}`}
                  className="-mx-2 grid grid-cols-[28px_minmax(0,1fr)_auto] items-center gap-x-2.5 gap-y-1 rounded-xl px-2 py-2.5 transition-colors hover:bg-sunken/60"
                >
                  <span
                    aria-hidden
                    className={cn(
                      "row-span-2 grid size-7 place-items-center rounded-9 text-10 font-bold",
                      TONE[String(step)],
                    )}
                  >
                    {initials(role || member)}
                  </span>
                  <span className="min-w-0 truncate text-11.5 font-medium text-ink-3">
                    {role || member}
                  </span>
                  <span
                    className={cn(
                      "justify-self-end rounded-full px-2 py-0.5 text-11 font-semibold whitespace-nowrap",
                      TONE[String(step)],
                    )}
                  >
                    {step === "blocked" ? "Blocked" : STEPS[step]}
                  </span>
                  <span className="min-w-0 truncate text-13 font-semibold text-ink">
                    {card.title}
                  </span>
                  <Steps step={step} />
                </Link>
              </li>
            );
          })}
        </ul>
      )}
      <div className="mt-1.5 flex items-center justify-between gap-3 border-t border-line pt-1.5 text-11 text-ink-3">
        <span>To do → Running → Review → Done</span>
        <Link
          href={board}
          className="-mr-2 inline-flex min-h-9 items-center rounded-lg px-2 text-xs font-semibold whitespace-nowrap text-accent transition-colors hover:bg-accent-soft"
        >
          Open Kanban →
        </Link>
      </div>
    </section>
  );
}

/** The card's place on To do → Running → Review → Done: steps behind it are
 * filled dots, its own step a ring, the ones ahead faint (blocked: red ring
 * where it stopped, on Running). */
function Steps({ step }: { step: number | "blocked" }) {
  const at = step === "blocked" ? 1 : step;
  return (
    <span aria-hidden className="flex items-center gap-1 justify-self-end">
      {STEPS.map((s, i) => (
        <i
          key={s}
          className={cn(
            "size-1.5 rounded-full",
            i < at
              ? "bg-accent"
              : i === at
                ? step === "blocked"
                  ? "bg-panel shadow-ring-danger"
                  : step === 3
                    ? "bg-accent"
                    : "bg-panel shadow-ring-accent"
                : "bg-line-strong",
          )}
        />
      ))}
    </span>
  );
}
