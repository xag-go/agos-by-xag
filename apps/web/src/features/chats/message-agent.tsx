"use client";

import { useState, type ReactNode } from "react";
import type {
  ChatActivity,
  ChatMessage,
  ChatTurn,
  LiveTurn,
} from "@/data/types";
import { Markdown } from "@/shared/ui/markdown";
import { ActionCard } from "./action-card";
import { CapabilityCard } from "./capability-card";
import { VoteButtons } from "@/features/feedback/vote-buttons";
import { ReplyButton, SmallAction } from "./message-owner";
import { ApprovalCard } from "./approval-card";

export function AgentReply({
  workspaceId,
  chatId,
  turn,
  reply,
  retry,
  speaker,
  onReply,
  onDelete,
}: {
  workspaceId: string;
  chatId: number;
  turn: ChatTurn | null;
  reply: ChatMessage | null;
  retry: ReactNode;
  speaker?: string | null;
  onReply?: () => void;
  onDelete?: () => void;
}) {
  return (
    <li className="group/reply flex flex-col gap-2">
      {speaker && <SpeakerName name={speaker} />}
      {reply && (
        <div
          data-message-id={reply.id}
          data-message-from={speaker ?? "the agent"}
        >
          <Markdown
            text={reply.body}
            className="text-body leading-relaxed text-ink"
          />
        </div>
      )}
      {turn?.status === "stopped" && !reply && (
        <p className="text-sm text-ink-3">You stopped this answer.</p>
      )}
      {turn?.status === "failed" && (
        <p
          role="alert"
          className="self-start rounded-2xl bg-danger-soft px-3.5 py-2 text-sm text-danger"
        >
          The agent couldn&apos;t answer
          {turn.error ? `: ${turn.error}` : "."}
        </p>
      )}
      {turn?.requests?.map((r) => (
        <CapabilityCard key={r.id} workspaceId={workspaceId} request={r} />
      ))}
      {turn?.actions?.map((a) => (
        <ActionCard key={a.id} workspaceId={workspaceId} action={a} />
      ))}
      <div className="flex min-h-5 items-start gap-3">
        {reply && <CopyButton text={reply.body} />}
        {reply && onReply && <ReplyButton onReply={onReply} />}
        {reply && (
          <VoteButtons
            key={`${String(reply.id)}:${String(reply.vote)}`}
            workspaceId={workspaceId}
            kind="reply"
            target={`${String(chatId)}:${String(reply.id)}`}
            vote={reply.vote}
            subject={reply.body.slice(0, 300)}
            fade
          />
        )}
        {reply && onDelete && (
          <span className="opacity-0 transition-opacity group-hover/reply:opacity-100 focus-within:opacity-100">
            <SmallAction label="Delete" onClick={onDelete} />
          </span>
        )}
        {retry}
      </div>
    </li>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => {
            setCopied(false);
          }, 1500);
        });
      }}
      className="text-xs text-ink-3 opacity-0 transition-opacity group-hover/reply:opacity-100 hover:text-ink focus-visible:opacity-100"
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

/** What the agent is doing, in one quiet line (no tool details). */
function statusLine(activity: ChatActivity[]): string {
  const running = activity.findLast((a) => a.status === "running");
  if (!running) return activity.length ? "Working" : "Thinking";
  if (running.kind === "thinking") return "Thinking";
  if (running.kind === "subagent") return "Asking a helper";
  const t = running.title.toLowerCase();
  if (t.includes("voice")) return "Listening to your voice note";
  if (t.includes("web")) return "Searching the web";
  if (t.includes("file") || t.includes("searched")) return "Reading files";
  if (t.includes("command") || t.includes("code"))
    return "Working in the workspace";
  return "Working";
}

export function LiveReply({
  workspaceId,
  chatId,
  live,
  speaker,
}: {
  workspaceId: string;
  chatId: number;
  live: LiveTurn;
  speaker?: string | null;
}) {
  const waiting = live.activity.find(
    (a) => a.kind === "approval" && a.status === "waiting",
  );
  return (
    <li className="flex flex-col gap-2">
      {speaker && <SpeakerName name={speaker} />}
      {waiting && (
        <ApprovalCard
          workspaceId={workspaceId}
          chatId={chatId}
          item={waiting}
        />
      )}
      {live.text ? (
        <Markdown
          text={live.text}
          className="text-body leading-relaxed text-ink [&>*:last-child]:after:ml-0.5 [&>*:last-child]:after:inline-block [&>*:last-child]:after:h-4 [&>*:last-child]:after:w-[3px] [&>*:last-child]:after:animate-pulse [&>*:last-child]:after:rounded-full [&>*:last-child]:after:bg-accent [&>*:last-child]:after:align-[-2px] [&>*:last-child]:after:content-['']"
        />
      ) : (
        !waiting && <Working label={statusLine(live.activity)} />
      )}
    </li>
  );
}

/** Who is talking, in a DM or a group (Workers). */
function SpeakerName({ name }: { name: string }) {
  return (
    <span className="flex items-center gap-2 text-sm font-medium text-ink">
      <span
        aria-hidden
        className="flex size-6 items-center justify-center rounded-lg bg-accent-soft text-xs font-semibold text-accent"
      >
        {name.slice(0, 1).toUpperCase()}
      </span>
      {name}
    </span>
  );
}

export function Working({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-2.5 text-sm text-ink-3">
      <span className="relative flex size-2.5" aria-hidden>
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-accent/50" />
        <span className="relative inline-flex size-2.5 rounded-full bg-accent" />
      </span>
      <span className="animate-pulse">{label}…</span>
    </span>
  );
}
