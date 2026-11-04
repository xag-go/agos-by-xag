"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import type {
  CardService,
  Chat,
  KanbanBoard,
  KanbanCardDetail,
} from "@/data/types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { DialogCloseButton, RouteDialog } from "@/shared/ui/dialog";
import { Select, Textarea } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { Tabs } from "@/shared/ui/tabs";
import { actOnCard, assignCard, setCardGoal } from "./card-actions";
import { DocumentsTab } from "./card-docs";
import { CardServices } from "./card-services";
import { LinkChipsProvider } from "./link-chips";
import { ReviewTab, reviewChipText } from "./card-review";
import { kanbanStatusLabel } from "./kanban-columns";
import type { BoardLabel } from "./labels";
import { landing, withChanges } from "./optimistic";
import { usePendingCards } from "./pending-cards";
import { AskRow, Waiting } from "./card-asks";
import { ChatTab, CommentsTab, DescriptionBody, PlanTab } from "./card-tabs";
import { CardFacts, CardLabels, Watchers } from "./card-facts";
import { SubtreeControls } from "./card-subtree";

/** A Kanban card (Hermes's Kanban), in the Kanban's task design. */
export function CardModal({
  workspaceId,
  card,
  chat,
  members,
  labels,
  closeHref,
  openDoc,
  services = [],
}: {
  workspaceId: string;
  card: KanbanCardDetail;
  chat: Chat | null;
  members: KanbanBoard["members"];
  /** The workspace's labels (Settings → Labels). */
  labels: BoardLabel[];
  closeHref: string;
  /** `?doc=<key>`: the modal opens on that document (the card body links them). */
  openDoc?: string;
  /** The dev servers / previews its worker started (step 59). */
  services?: CardService[];
}) {
  const [busy, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  // Mark done on a card Hermes won't finish without words: the box is open.
  const [asking, setAsking] = useState(false);
  const [words, setWords] = useState("");
  const pending = usePendingCards();
  // The card as the screen shows it: Hermes's, with the clicks whose write is
  // still running on it (they end with the click: then only Hermes's is left).
  const shown = withChanges(card, pending.changes);
  const run = (
    task: () => Promise<{ error: string | null }>,
    ok?: () => void,
  ) => {
    start(async () => {
      const said = (await task()).error;
      // Inside the click's transition (an update after an await is not, by
      // itself): a refusal shows in the same frame the card goes back.
      start(() => {
        setError(said);
        if (!said) ok?.();
      });
    });
  };
  // Where the card goes after a button or his answer, shown at once inside the
  // click's transition (nothing early when the screen can't tell for sure).
  const moveTo = (action: "unblock" | "archive" | "done" | "block") => {
    const status = pending.board && landing(action, card, pending.board);
    if (status) pending.show({ card: card.id, status, blockKind: "" });
  };
  const act = (
    action: "unblock" | "archive" | "done" | "block",
    summary?: string,
  ) => {
    run(
      () => {
        moveTo(action);
        return actOnCard(workspaceId, card.id, action, summary);
      },
      () => {
        setAsking(false);
        setWords("");
      },
    );
  };
  // What he may do with it now: the core's rule over Hermes's statuses.
  const can = (action: "unblock" | "archive" | "done" | "block") =>
    (card.actions ?? []).includes(action);
  // Hermes's own dashboard asks for a completion summary first; the core says
  // where Hermes refuses a card without one (review and a card with its result
  // go as they are).
  const askDone = asking && can("done");
  const asks = card.status === "blocked" && card.blockKind === "needs_input";
  const shownAsks =
    shown.status === "blocked" && shown.blockKind === "needs_input";
  const label = "text-11 font-medium tracking-caps text-ink-3 uppercase";
  // The Kanban's view stays in the URL (closeHref carries it).
  const here = (extra: string) =>
    `${closeHref}${closeHref.includes("?") ? "&" : "?"}card=${encodeURIComponent(card.id)}${extra}`;
  return (
    <RouteDialog closeHref={closeHref} label={card.title} size="xl">
      <LinkChipsProvider
        workspaceId={workspaceId}
        texts={[
          card.body,
          card.summary ?? "",
          ...card.comments.map((c) => c.body),
        ]}
      >
        <div className="flex h-[min(92dvh,58rem)] flex-col">
          <header className="flex items-start gap-3 border-b border-line px-6 py-4 max-md:px-4">
            <div className="min-w-0 flex-1">
              <p className="flex flex-wrap items-center gap-2 text-xs text-ink-3">
                <span className="font-mono">{card.id}</span>
                <span className="inline-flex items-center gap-1.5 rounded-md bg-sunken px-1.5 py-0.5 font-medium text-ink-2">
                  <span
                    aria-hidden="true"
                    className={cn(
                      "size-1.5 rounded-full",
                      shown.status === "running" && "bg-success",
                      shown.status === "blocked" && "bg-danger",
                      shown.status === "done" && "bg-ink",
                      !["running", "blocked", "done"].includes(shown.status) &&
                        "border border-ink-3",
                    )}
                  />
                  {kanbanStatusLabel(shown.status, card.statusLabel)}
                </span>
                {shownAsks && (
                  <span className="rounded-md bg-attention px-1.5 py-0.5 font-medium text-attention-ink">
                    ❓ Needs your answer
                  </span>
                )}
                {card.goal && (
                  <span className="rounded-md bg-sunken px-1.5 py-0.5 text-ink-2">
                    Goal mode
                  </span>
                )}
                {reviewChipText(card.reviewChip) && (
                  <span className="rounded-md bg-sunken px-1.5 py-0.5 text-ink-2">
                    {reviewChipText(card.reviewChip)}
                  </span>
                )}
              </p>
              <h2 className="mt-1 font-display text-xl leading-snug font-semibold tracking-title">
                {card.title}
              </h2>
            </div>
            <DialogCloseButton />
          </header>

          {(card.asks ?? []).map((a) => (
            <AskRow key={a.id} workspaceId={workspaceId} ask={a} />
          ))}
          {/* Hermes's card, not the shown one: the answer form stays (with its
            "Sending…" and, on a failed write, its error) until Hermes took it. */}
          {card.status === "blocked" && (
            <Waiting
              workspaceId={workspaceId}
              cardId={card.id}
              question={card.question}
              asks={asks}
              onAnswer={() => {
                moveTo("unblock");
              }}
            />
          )}

          <div className="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)_auto] md:grid-cols-[minmax(0,1fr)_19rem] md:grid-rows-1">
            {/* Left: the work itself */}
            <div className="flex min-h-0 min-w-0 flex-col">
              <Tabs
                initial={openDoc ? "documents" : undefined}
                items={[
                  {
                    id: "description",
                    label: "Description",
                    content: (
                      <DescriptionBody
                        card={card}
                        docHref={(key) =>
                          here(`&doc=${encodeURIComponent(key)}`)
                        }
                      />
                    ),
                  },
                  {
                    id: "documents",
                    label: "Documents",
                    count: card.documents?.length ?? 0,
                    content: (
                      <DocumentsTab
                        workspaceId={workspaceId}
                        card={card}
                        initialKey={openDoc}
                      />
                    ),
                  },
                  {
                    id: "review",
                    label: "Review",
                    count: card.review?.ownerCan?.length ?? 0,
                    content: (
                      <ReviewTab
                        workspaceId={workspaceId}
                        card={card}
                        members={members}
                        planHref={here("&doc=plan")}
                      />
                    ),
                  },
                  {
                    id: "plan",
                    label: "Steps",
                    count: card.plan?.length ?? 0,
                    content: <PlanTab card={card} />,
                  },
                  {
                    id: "comments",
                    label: "Comments",
                    count: card.comments.length,
                    content: (
                      <CommentsTab
                        workspaceId={workspaceId}
                        card={card}
                        members={members}
                        cardHref={(id) =>
                          `${closeHref}${closeHref.includes("?") ? "&" : "?"}card=${encodeURIComponent(id)}`
                        }
                      />
                    ),
                  },
                  {
                    id: "chat",
                    label: "Chat",
                    count: chat?.messages.length ?? 0,
                    content: (
                      <ChatTab
                        workspaceId={workspaceId}
                        card={card}
                        chat={chat}
                      />
                    ),
                  },
                ]}
              />
            </div>

            {/* Right: who, where it stands, what to do */}
            <aside className="flex max-h-[40dvh] min-h-0 flex-col border-t border-line bg-sunken/40 md:max-h-none md:border-t-0 md:border-l">
              <div className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto px-5 py-5 max-md:px-4 max-md:py-4">
                <CardServices
                  workspaceId={workspaceId}
                  services={services}
                  labelClass={label}
                />
                <section className="flex flex-col gap-2">
                  <p className={label}>Member</p>
                  <Select
                    aria-label="Member"
                    value={shown.member}
                    disabled={busy || !can("done")}
                    onChange={(e) => {
                      const member = e.currentTarget.value;
                      run(() => {
                        pending.show({
                          card: card.id,
                          member,
                          memberTitle:
                            members.find((m) => m.name === member)?.title ?? "",
                        });
                        return assignCard(workspaceId, card.id, member);
                      });
                    }}
                  >
                    <option value="">Nobody yet</option>
                    {members.map((m) => (
                      <option key={m.name} value={m.name}>
                        {m.title}
                      </option>
                    ))}
                  </Select>
                  {card.model && (
                    <p className="text-xs text-ink-3">Model: {card.model}</p>
                  )}
                  {card.chainStalled && (
                    <p className="text-xs text-attention-ink">
                      Team stalled: {card.chainStalled}.
                    </p>
                  )}
                </section>

                <section className="flex flex-col gap-2">
                  <p className={label}>Goal</p>
                  <Select
                    aria-label="Goal"
                    value={
                      card.goalId !== null &&
                      card.goalId !== undefined &&
                      !card.goalInherited
                        ? String(card.goalId)
                        : ""
                    }
                    disabled={busy || (card.goals ?? []).length === 0}
                    onChange={(e) => {
                      const next = e.currentTarget.value;
                      run(() =>
                        setCardGoal(
                          workspaceId,
                          card.id,
                          next ? Number(next) : null,
                        ),
                      );
                    }}
                  >
                    <option value="">
                      {card.goalInherited && card.goalId !== null
                        ? `From its parent: ${
                            (card.goals ?? []).find((g) => g.id === card.goalId)
                              ?.title ?? `#${String(card.goalId)}`
                          }`
                        : (card.goals ?? []).length === 0
                          ? "No Vision yet"
                          : "No goal"}
                    </option>
                    {(card.goals ?? [])
                      .filter(
                        (g) => g.status === "active" || g.id === card.goalId,
                      )
                      .map((g) => (
                        <option key={g.id} value={String(g.id)}>
                          {g.level === "project"
                            ? "Project"
                            : g.level === "vision"
                              ? "Vision"
                              : "Goal"}{" "}
                          #{g.id}: {g.title}
                        </option>
                      ))}
                  </Select>
                  {(card.skillPins?.length ?? 0) > 0 && (
                    <p className="text-xs text-ink-3">
                      Skills loaded:{" "}
                      {(card.skillPins ?? []).map((p, i) => (
                        <span key={p.skill}>
                          {i > 0 && ", "}
                          <Link
                            href={`/w/${encodeURIComponent(workspaceId)}/settings/capabilities`}
                            className="font-mono hover:text-ink"
                          >
                            {p.skill} v{p.version}
                          </Link>
                        </span>
                      ))}
                    </p>
                  )}
                </section>

                <CardLabels
                  workspaceId={workspaceId}
                  card={card}
                  labels={labels}
                  busy={busy}
                  run={run}
                />

                <Watchers
                  workspaceId={workspaceId}
                  card={card}
                  members={members}
                  busy={busy}
                  run={run}
                />

                <div className="border-t border-line" />

                <CardFacts workspaceId={workspaceId} card={card} />
              </div>
              {((card.actions ?? []).length > 0 || error) && (
                <div className="flex flex-col gap-2 border-t border-line bg-panel px-5 py-4 max-md:px-4 max-md:pb-[max(1rem,env(safe-area-inset-bottom))]">
                  {askDone ? (
                    <form
                      className="flex flex-col gap-2"
                      onSubmit={(e) => {
                        e.preventDefault();
                        if (words.trim()) act("done", words);
                      }}
                    >
                      <p className="text-sm font-medium">What was done?</p>
                      <Textarea
                        name="text"
                        rows={2}
                        aria-label="What was done?"
                        placeholder="What was done"
                        required
                        autoFocus
                        value={words}
                        onChange={(e) => {
                          setWords(e.currentTarget.value);
                        }}
                      />
                      <FormStatus error={error} />
                      <div className="flex items-center justify-end gap-2">
                        <Button
                          type="button"
                          variant="ghost"
                          disabled={busy}
                          onClick={() => {
                            setAsking(false);
                            setWords("");
                            setError(null);
                          }}
                        >
                          Cancel
                        </Button>
                        <Button
                          type="submit"
                          variant="primary"
                          disabled={busy || !words.trim()}
                        >
                          {busy ? "Sending…" : "Mark done"}
                        </Button>
                      </div>
                    </form>
                  ) : (
                    <>
                      <div className="grid grid-cols-2 gap-2 max-md:[&>button]:!h-11 [&>*:only-child]:col-span-2">
                        {can("unblock") && !asks && (
                          <Button
                            type="button"
                            variant="primary"
                            disabled={busy}
                            onClick={() => {
                              act("unblock");
                            }}
                          >
                            Unblock
                          </Button>
                        )}
                        {can("done") && (
                          <Button
                            type="button"
                            variant={
                              card.status === "review" ? "primary" : undefined
                            }
                            disabled={busy}
                            onClick={() => {
                              if (card.doneNeedsSummary) {
                                setError(null);
                                setAsking(true);
                              } else act("done");
                            }}
                          >
                            Mark done
                          </Button>
                        )}
                        {can("block") && (
                          <Button
                            type="button"
                            disabled={busy}
                            onClick={() => {
                              act("block");
                            }}
                          >
                            Stop
                          </Button>
                        )}
                        {can("archive") && (
                          <Button
                            type="button"
                            variant="ghost"
                            disabled={busy}
                            onClick={() => {
                              act("archive");
                            }}
                          >
                            Archive
                          </Button>
                        )}
                      </div>
                      <SubtreeControls
                        workspaceId={workspaceId}
                        card={card}
                        busy={busy}
                        run={run}
                      />
                      {error && <FormStatus error={error} />}
                    </>
                  )}
                </div>
              )}
            </aside>
          </div>
        </div>
      </LinkChipsProvider>
    </RouteDialog>
  );
}
