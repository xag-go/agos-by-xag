"use client";

import Link from "next/link";
import { useEffect, useState, useTransition } from "react";
import type { Inbox, InboxItem } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { markItem, undoProposal, unmarkItem } from "./actions";
import { typing } from "@/shared/keyboard";
import type { Decided } from "./proposal-card";
import { Item, TYPE_LABEL } from "./inbox-item";

type Toast = {
  id: string;
  words: string;
  at: number;
  undo?: () => Promise<{ error: string | null }>;
  undone?: boolean;
  error?: string;
  /** An approved hire's Undo (the member goes). */
  proposal?: Decided;
};

/**
 * Everything waiting for the owner in this workspace, one list from the core:
 * the agents' proposals (hires, instruction changes, plans), their typed
 * questions, the cards' Allow once / Deny asks, the cards Hermes holds blocked
 * for him, the cards whose blocker chain stalled, and Hermes's own Allow / Deny
 * cards waiting in a chat. Each item is a Hermes Kanban card (or a chat); the
 * answer goes on the card and the agent carries on.
 *
 * Keyboard: j / k move, a / r approve / reject the focused proposal, e dismisses
 * (with Undo in the toast). What he just decided leaves the list at once.
 */
export function InboxView({
  workspaceId,
  inbox,
}: {
  workspaceId: string;
  inbox: Inbox;
}) {
  const [hidden, setHidden] = useState<Set<string>>(() => new Set());
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [focus, setFocus] = useState(0);
  const [, start] = useTransition();
  const items = inbox.items.filter((i) => !i.dismissed && !hidden.has(i.key));
  const focusedKey = items[Math.min(focus, items.length - 1)]?.key;

  const toast = (t: Omit<Toast, "at">) => {
    setToasts((list) => [...list.slice(-2), { ...t, at: Date.now() }]);
  };
  const drop = (key: string) => {
    setHidden((was) => new Set([...was, key]));
  };
  const decided = (d: Decided) => {
    drop(`ask:${String(d.id)}`);
    toast({
      id: `ask:${String(d.id)}`,
      words:
        d.choice === "approve"
          ? `Approved: ${d.label}.`
          : d.choice === "revise"
            ? `Sent back: ${d.label}.`
            : `Rejected: ${d.label}.`,
      proposal: d,
    });
  };
  const dismiss = (item: InboxItem) => {
    drop(item.key);
    start(async () => {
      const r = await markItem(workspaceId, item.key, "dismissed");
      toast({
        id: item.key,
        words: r.error ?? `Dismissed: ${item.title}.`,
        error: r.error ?? undefined,
        undo: r.error
          ? undefined
          : async () => {
              const u = await unmarkItem(workspaceId, item.key, "dismissed");
              if (!u.error) {
                setHidden((was) => {
                  const next = new Set(was);
                  next.delete(item.key);
                  return next;
                });
              }
              return u;
            },
      });
    });
  };
  const seen = (item: InboxItem) => {
    if (item.read) return;
    start(async () => {
      await markItem(workspaceId, item.key, "read");
    });
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (typing(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "j") setFocus((f) => Math.min(f + 1, items.length - 1));
      else if (e.key === "k") setFocus((f) => Math.max(f - 1, 0));
      else if (e.key === "e" && focusedKey) {
        const item = items.find((i) => i.key === focusedKey);
        if (item) dismiss(item);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  });

  return (
    <div className="flex flex-col gap-4">
      <p className="max-w-xl text-sm text-ink-2">
        What the team waits on you for: Kanban cards (your answer goes on the
        card and the agent carries on) and changes an agent wants to make to its
        memory or skills.{" "}
        <span className="text-ink-3">
          j / k move · a / r decide · e dismiss
        </span>
      </p>
      {items.length === 0 && (
        <p className="rounded-2xl border border-dashed border-line px-4 py-8 text-center text-sm text-ink-3">
          Nothing waits for you.
        </p>
      )}
      <ul className="flex flex-col gap-3">
        {items.map((item) => (
          <li
            key={item.key}
            className="group relative flex flex-col gap-1"
            onMouseEnter={() => {
              seen(item);
            }}
            onFocus={() => {
              seen(item);
            }}
          >
            <div className="flex items-center gap-2 text-xs text-ink-3">
              {!item.read && <UnreadDot />}
              <span>
                {item.held?.subsystem === "skills"
                  ? "Skill change"
                  : TYPE_LABEL[item.type]}
              </span>
              {item.card && (
                <Link
                  href={`/w/${encodeURIComponent(workspaceId)}/kanban?card=${encodeURIComponent(item.card)}`}
                  className="hover:text-ink hover:underline"
                >
                  card {item.card}
                </Link>
              )}
              <Button
                variant="ghost"
                className="ml-auto h-6 px-1.5 text-xs opacity-0 group-hover:opacity-100 focus:opacity-100"
                onClick={() => {
                  dismiss(item);
                }}
              >
                Dismiss
              </Button>
            </div>
            <Item
              workspaceId={workspaceId}
              item={item}
              focused={item.key === focusedKey}
              onDecided={decided}
              onAnswered={(label) => {
                drop(item.key);
                toast({ id: item.key, words: `Answered: ${label}.` });
              }}
              onDone={(words) => {
                drop(item.key);
                toast({ id: item.key, words });
              }}
            />
          </li>
        ))}
      </ul>
      <Toasts workspaceId={workspaceId} toasts={toasts} onChange={setToasts} />
    </div>
  );
}

const TOAST_MS = 12_000;

/** The dot before an unread item's date, named for a screen reader. */
function UnreadDot() {
  return (
    <span
      role="img"
      aria-label="Unread"
      className="inline-block size-1.5 rounded-full bg-accent"
    />
  );
}

function Toasts({
  workspaceId,
  toasts,
  onChange,
}: {
  workspaceId: string;
  toasts: Toast[];
  onChange: (next: Toast[]) => void;
}) {
  const [busy, start] = useTransition();
  useEffect(() => {
    if (toasts.length === 0) return;
    const timer = setTimeout(() => {
      const now = Date.now();
      onChange(toasts.filter((t) => now - t.at < TOAST_MS));
    }, TOAST_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [toasts, onChange]);
  if (toasts.length === 0) return null;
  const update = (id: string, patch: Partial<Toast>) => {
    onChange(
      toasts.map((x) => (x.id === id ? { ...x, ...patch, at: Date.now() } : x)),
    );
  };
  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed bottom-4 left-1/2 z-40 flex -translate-x-1/2 flex-col gap-2"
    >
      {toasts.map((t) => {
        const canUndo =
          !t.undone && !t.error && (t.undo || t.proposal?.canUndo);
        return (
          <div
            key={t.id}
            className="pointer-events-auto flex items-center gap-3 rounded-xl bg-ink px-4 py-2 text-sm text-paper shadow-lg"
          >
            <span>
              {t.undone ? `Undone: ${t.words}` : (t.error ?? t.words)}
            </span>
            {canUndo && (
              <Button
                variant="ghost"
                className="h-7 px-2 text-paper hover:bg-paper/10 hover:text-paper"
                disabled={busy}
                onClick={() => {
                  start(async () => {
                    const r = t.undo
                      ? await t.undo()
                      : await undoProposal(workspaceId, t.proposal?.id ?? 0);
                    update(t.id, {
                      undone: !r.error,
                      error: r.error ?? undefined,
                    });
                  });
                }}
              >
                Undo
              </Button>
            )}
          </div>
        );
      })}
    </div>
  );
}
