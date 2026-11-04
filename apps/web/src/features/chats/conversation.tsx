"use client";

import { useRouter } from "next/navigation";
import {
  useEffect,
  useLayoutEffect,
  useOptimistic,
  useRef,
  useState,
  useTransition,
} from "react";
import type {
  Chat,
  ChatMessage,
  LiveTurn,
  LiveView,
  OffLine,
} from "@/data/types";
import { Button } from "@/shared/ui/button";
import { useAsk } from "@/shared/ui/confirm";
import { KanbanAsks } from "./kanban-asks";
import {
  deleteChatMessage,
  editChatMessage,
  sendChatMessage,
  stopChat,
  type OutgoingAttachment,
} from "./actions";
import { Composer } from "./composer";
import type { Draft, ReplyTarget } from "./composer-types";
import { EditMessageDialog, type EditChoice } from "./edit-message-dialog";
import { SelectionReply } from "./selection-reply";
import { wakeNow } from "@/features/workspaces/work-hours-actions";
import {
  OwnerMessage,
  quoteName,
  target,
  type ShownAttachment,
} from "./message-owner";
import {
  Stopper,
  getJson,
  sleep,
  timeline,
  untilShown,
} from "./conversation-poll";
import { EmptyChat } from "./empty-chat";
import { AgentReply, LiveReply, Working } from "./message-agent";
import { RetryButton } from "./approval-card";

type Props = {
  workspaceId: string;
  chat: Chat;
  mentionable?: { name: string; title: string }[];
  placeholder?: string;
  /** Workers: agent name → shown name; the Co-Founder is under "". */
  people?: Record<string, string>;
};

/**
 * One conversation, answers only: the owner's messages on the right, the
 * agent's replies on the left. What the agent does in the background stays out
 * of sight — while it works you see one quiet status line, then the answer.
 */
export function Conversation({
  workspaceId,
  chat,
  people,
  mentionable,
  placeholder,
}: Props) {
  const who = (speaker: string | null | undefined): string | null =>
    people ? (people[speaker ?? ""] ?? speaker ?? null) : null;
  const router = useRouter();
  const [live, setLive] = useState<LiveTurn | null>(null);
  const [asks, setAsks] = useState<NonNullable<LiveView["asks"]>>([]);
  const [tokens, setTokens] = useState<NonNullable<LiveView["tokens"]>>([]);
  const [questions, setQuestions] = useState<
    NonNullable<LiveView["questions"]>
  >([]);
  const [pending, setPending] = useState(chat.pending || chat.working);
  // The chat's agent is off-hours: his messages wait for its check-in.
  const [off, setOff] = useState<OffLine | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [replyTo, setReplyTo] = useState<ReplyTarget | null>(null);
  const [optimistic, addOptimistic] = useOptimistic(
    chat.messages,
    (messages: ChatMessage[], draft: Draft): ChatMessage[] => [
      ...messages,
      {
        id: -Date.now(),
        at: new Date().toISOString(),
        from: "owner",
        kind: "chat",
        body: draft.text,
        replyTo: draft.replyTo?.id ?? null,
        replyPreview: draft.replyTo?.excerpt ?? draft.replyTo?.preview ?? null,
        replyExcerpt: draft.replyTo?.excerpt ?? null,
        editedAt: null,
        replyFrom: draft.replyTo?.from ?? null,
        vote: 0,
        attachments: draft.files.map((f, i): ShownAttachment => ({
          id: -i - 1,
          kind: f.kind,
          name: f.name,
          mime: f.mime,
          size: f.size,
          duration: f.duration ?? null,
          transcript: null,
          preview: f.preview,
        })),
      },
    ],
  );
  const busy = live !== null || (pending && off === null);
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  // Follow the answer being written (long-poll of the core). When an answer
  // ends, the page data refreshes so the saved reply replaces the live one.
  // A hidden tab asks nothing; shown again, it asks at once (after=version
  // picks up where it left, so no answer is missed).
  useEffect(() => {
    let stopped = false;
    let version = -1;
    let hadLive = false;
    const controller = new Stopper();
    async function loop() {
      let failures = 0;
      while (!stopped) {
        await untilShown(controller);
        if (stopped) return;
        try {
          const view = await getJson<LiveView>(
            `/api/w/${encodeURIComponent(workspaceId)}/chats/${String(chat.id)}/live?after=${String(version)}`,
            controller,
          );
          failures = 0;
          if (stopped) return;
          setLive(view.live);
          setPending(view.pending);
          setOff(view.off ?? null);
          setAsks(view.asks ?? []);
          setQuestions(view.questions ?? []);
          setTokens(view.tokens ?? []);
          if (view.live) {
            hadLive = true;
            version = view.live.version;
          } else {
            version = -1;
            if (hadLive) {
              hadLive = false;
              router.refresh();
            }
            // The core held the ask until something changed: ask again at once
            // (an older core answered at once, so it waited here between asks).
            if (!view.held) await sleep(view.pending ? 400 : 4000, controller);
          }
        } catch {
          if (stopped) return;
          failures += 1;
          await sleep(Math.min(8000, 800 * failures), controller);
        }
      }
    }
    void loop();
    return () => {
      stopped = true;
      controller.stop();
    };
  }, [workspaceId, chat.id, router]);

  // Stay pinned to the bottom unless the owner scrolled up to read.
  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  });

  const [sending, startSending] = useTransition();
  function send(draft: Draft) {
    if (!draft.text.trim() && draft.files.length === 0) return;
    setError(null);
    stick.current = true;
    startSending(async () => {
      addOptimistic(draft);
      setPending(true);
      const files: OutgoingAttachment[] = draft.files.map((f) => ({
        kind: f.kind,
        name: f.name,
        mime: f.mime,
        data: f.data,
        ...(f.duration !== undefined ? { duration: f.duration } : {}),
      }));
      setReplyTo(null);
      const result = await sendChatMessage(
        workspaceId,
        chat.id,
        draft.text,
        files,
        draft.replyTo?.id ?? null,
        draft.replyTo?.excerpt ?? null,
      );
      if (result.error) setError(result.error);
    });
  }

  const { dialog, confirm } = useAsk();
  const [editing, setEditing] = useState<ChatMessage | null>(null);
  // The agent answered a message when a later reply (or turn) exists after it.
  const answeredIds = new Set(
    chat.messages
      .filter(
        (m) =>
          m.from === "owner" &&
          chat.turns.some(
            (t) => t.askedUpTo >= m.id && t.status === "completed",
          ),
      )
      .map((m) => m.id),
  );
  async function saveEdit(message: ChatMessage, choice: EditChoice | null) {
    setEditing(null);
    if (!choice) return;
    if (choice.text === message.body.trim() && !choice.reanswer) return;
    if (choice.reanswer) {
      stick.current = true;
      setPending(true);
    }
    const result = await editChatMessage(
      workspaceId,
      chat.id,
      message.id,
      choice.text,
      choice.reanswer,
    );
    if (result.error) {
      setError(result.error);
      setPending(false);
    }
  }
  async function deleteMessage(message: ChatMessage) {
    const ok = await confirm({
      title: "Delete this message?",
      body: "It's removed from this chat. Replies to it stay.",
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    const result = await deleteChatMessage(workspaceId, chat.id, message.id);
    if (result.error) setError(result.error);
  }

  const [stopping, startStopping] = useTransition();
  function stop() {
    startStopping(async () => {
      const result = await stopChat(workspaceId, chat.id);
      if (result.error) setError(result.error);
      else {
        // Stopped in AGOS right away: don't wait for the live view to notice.
        setLive(null);
        setPending(false);
      }
    });
  }

  const items = timeline(optimistic, chat.turns);
  const lastTurn = chat.turns.at(-1);
  const canRetry =
    !busy &&
    lastTurn !== undefined &&
    (lastTurn.status === "failed" || lastTurn.status === "stopped");

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {dialog}
      {editing && (
        <EditMessageDialog
          initial={editing.body}
          answered={answeredIds.has(editing.id)}
          busy={busy}
          onDone={(choice) => void saveEdit(editing, choice)}
        />
      )}
      <SelectionReply
        container={scroller}
        onReply={({ id, from, excerpt }) => {
          setReplyTo({ id, from, preview: excerpt, excerpt });
        }}
      />
      <div
        ref={scroller}
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        }}
        className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-8"
        aria-live="polite"
      >
        {items.length === 0 && !live ? (
          <EmptyChat
            title={chat.title}
            onPick={(text) => {
              send({ text, files: [] });
            }}
          />
        ) : (
          <ol className="flex w-full flex-col gap-6">
            {items.map((item) =>
              item.kind === "owner" ? (
                <OwnerMessage
                  key={`m${String(item.message.id)}`}
                  workspaceId={workspaceId}
                  chatId={chat.id}
                  message={item.message}
                  quotedFrom={quoteName(item.message.replyFrom, who)}
                  onReply={() => {
                    setReplyTo(target(item.message, "you"));
                  }}
                  onEdit={() => {
                    setEditing(item.message);
                  }}
                  onDelete={() => void deleteMessage(item.message)}
                />
              ) : (
                <AgentReply
                  key={`t${item.key}`}
                  workspaceId={workspaceId}
                  chatId={chat.id}
                  turn={item.turn}
                  reply={item.reply}
                  speaker={who(item.reply?.speaker ?? item.turn?.speaker)}
                  onReply={
                    item.reply
                      ? () => {
                          if (item.reply)
                            setReplyTo(
                              target(
                                item.reply,
                                who(item.reply.speaker) ?? "the agent",
                              ),
                            );
                        }
                      : undefined
                  }
                  onDelete={
                    item.reply
                      ? () => {
                          if (item.reply) void deleteMessage(item.reply);
                        }
                      : undefined
                  }
                  retry={
                    canRetry && item.turn?.id === lastTurn.id ? (
                      <RetryButton workspaceId={workspaceId} chatId={chat.id} />
                    ) : null
                  }
                />
              ),
            )}
            {live ? (
              <LiveReply
                workspaceId={workspaceId}
                chatId={chat.id}
                live={live}
                speaker={who(live.speaker)}
              />
            ) : (
              pending &&
              off === null && (
                <li>
                  <Working label="Starting" />
                </li>
              )
            )}
          </ol>
        )}
      </div>
      {off && (
        <OffBar
          workspaceId={workspaceId}
          off={off}
          onWoke={() => {
            setOff(null);
            router.refresh();
          }}
        />
      )}
      <KanbanAsks
        workspaceId={workspaceId}
        asks={asks}
        questions={questions}
        tokens={tokens}
      />
      <Composer
        workspaceId={workspaceId}
        chat={chat}
        busy={busy}
        sending={sending}
        stopping={stopping}
        error={error}
        onError={setError}
        onSend={send}
        onStop={stop}
        replyTo={replyTo}
        onCancelReply={() => {
          setReplyTo(null);
        }}
        mentionable={mentionable}
        placeholder={placeholder}
      />
    </div>
  );
}

/** The agent is off-hours (Settings → Work hours): when it checks in, and Wake
 * now (on for today, the same as picking it to stay on). */
function OffBar({
  workspaceId,
  off,
  onWoke,
}: {
  workspaceId: string;
  off: OffLine;
  onWoke: () => void;
}) {
  const [waking, startWaking] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const until = off.untilText ? `Off until ${off.untilText}` : "Off right now";
  return (
    <div
      role="status"
      className="mx-4 mb-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-xl bg-sunken px-3.5 py-2 text-sm text-ink-2 sm:mx-8"
    >
      <span className="min-w-0 flex-1 text-pretty tabular-nums">
        <span className="font-medium text-ink">{until}</span> — your message
        will be answered at check-in.
      </span>
      {error && <span className="text-xs text-danger">{error}</span>}
      <Button
        disabled={waking}
        className="active:scale-[0.96]"
        onClick={() => {
          startWaking(async () => {
            const result = await wakeNow(workspaceId, off.agent);
            if (result.error) setError(result.error);
            else onWoke();
          });
        }}
      >
        {waking ? "Waking…" : "Wake now"}
      </Button>
    </div>
  );
}
