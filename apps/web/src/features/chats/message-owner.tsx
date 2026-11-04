"use client";

import type { ChatAttachment, ChatMessage } from "@/data/types";
import { cn } from "@/shared/ui/cn";
import type { ReplyTarget } from "./composer-types";
import { VoiceNote } from "./voice-note";
import { FileChip } from "./file-chip";

// ---- messages -------------------------------------------------------------------

export type ShownAttachment = ChatAttachment & { preview?: string };

function fileUrl(
  workspaceId: string,
  chatId: number,
  a: ShownAttachment,
): string {
  if (a.preview) return a.preview;
  return `/api/w/${encodeURIComponent(workspaceId)}/chats/${String(chatId)}/files/${String(a.id)}`;
}

/** The message being answered, as shown in the reply bar. */
export function target(message: ChatMessage, from: string): ReplyTarget {
  const text = message.body.replace(/\s+/g, " ").trim();
  return {
    id: message.id,
    from,
    preview: text ? text.slice(0, 160) : "Attachment",
  };
}

export function quoteName(
  from: string | null | undefined,
  who: (speaker: string | null | undefined) => string | null,
): string {
  if (!from) return "";
  if (from === "owner") return "You";
  if (from === "agent") return who(null) ?? "The agent";
  return who(from) ?? from;
}

/** The message a reply answers, small, above the reply. */
function Quote({
  from,
  text,
  mine,
  part,
}: {
  from: string;
  text: string;
  mine?: boolean;
  /** Only a selected part of the message was answered. */
  part?: boolean;
}) {
  return (
    <div
      className={cn(
        "max-w-[85%] rounded-xl border-l-3 px-3 py-1.5 text-sm sm:max-w-[75%]",
        mine
          ? "border-accent-ink/60 bg-accent-ink/10 text-accent-ink/85"
          : "border-accent bg-sunken text-ink-2",
      )}
    >
      {from && (
        <p className="text-xs font-medium">
          {from}
          {part && <span className="font-normal opacity-75"> · a part</span>}
        </p>
      )}
      <p className={cn("line-clamp-2 whitespace-pre-wrap", part && "italic")}>
        {part ? `“${text}”` : text}
      </p>
    </div>
  );
}

export function SmallAction({
  label,
  onClick,
}: {
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-xs text-ink-3 hover:text-ink"
    >
      {label}
    </button>
  );
}

export function ReplyButton({ onReply }: { onReply: () => void }) {
  return (
    <button
      type="button"
      onClick={onReply}
      className="flex items-center gap-1 text-xs text-ink-3 hover:text-ink"
    >
      <svg viewBox="0 0 16 16" className="size-3.5" fill="none" aria-hidden>
        <path
          d="M6.5 3.5 2.5 7.5l4 4M3 7.5h6.5a4 4 0 0 1 4 4v1"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      Reply
    </button>
  );
}

export function OwnerMessage({
  workspaceId,
  chatId,
  message,
  quotedFrom,
  onReply,
  onEdit,
  onDelete,
}: {
  workspaceId: string;
  chatId: number;
  message: ChatMessage;
  quotedFrom: string;
  onReply: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const shown = message.attachments as ShownAttachment[];
  const images = shown.filter((a) => a.kind === "image");
  const others = shown.filter((a) => a.kind !== "image");
  const sending = message.id < 0;
  return (
    <li
      className={cn(
        "group/owner flex flex-col items-end gap-1.5",
        sending && "opacity-70",
      )}
    >
      {images.length > 0 && (
        <div className="flex max-w-[85%] flex-wrap justify-end gap-1.5">
          {images.map((a) => (
            <a
              key={a.id}
              href={a.id > 0 ? fileUrl(workspaceId, chatId, a) : undefined}
              target="_blank"
              rel="noreferrer"
              className="block overflow-hidden rounded-2xl border border-line"
            >
              {/* eslint-disable-next-line @next/next/no-img-element -- private, same-origin file */}
              <img
                src={fileUrl(workspaceId, chatId, a)}
                alt={a.name}
                className="max-h-64 max-w-72 object-cover"
              />
            </a>
          ))}
        </div>
      )}
      {others.map((a) =>
        a.kind === "audio" ? (
          <VoiceNote
            key={a.id}
            src={a.id > 0 || a.preview ? fileUrl(workspaceId, chatId, a) : null}
            duration={a.duration ?? null}
            transcript={a.transcript ?? null}
          />
        ) : (
          <FileChip
            key={a.id}
            href={a.id > 0 ? fileUrl(workspaceId, chatId, a) : null}
            name={a.name}
            size={a.size}
          />
        ),
      )}
      {message.body && (
        <div className="flex max-w-[85%] flex-col items-end gap-1 rounded-3xl rounded-br-lg bg-accent px-4 py-2.5 text-body leading-relaxed whitespace-pre-wrap text-accent-ink sm:max-w-[75%]">
          {message.replyPreview && (
            <Quote
              from={quotedFrom}
              text={message.replyPreview}
              part={Boolean(message.replyExcerpt)}
              mine
            />
          )}
          <span
            className="self-stretch"
            data-message-id={message.id}
            data-message-from="you"
          >
            {message.body}
          </span>
        </div>
      )}
      {!sending && (
        <div className="flex h-4 items-center gap-3">
          {message.editedAt && (
            <span className="text-xs text-ink-3" title={message.editedAt}>
              Edited
            </span>
          )}
          <div className="flex items-center gap-3 opacity-0 transition-opacity group-hover/owner:opacity-100 focus-within:opacity-100">
            <ReplyButton onReply={onReply} />
            {message.body && <SmallAction label="Edit" onClick={onEdit} />}
            <SmallAction label="Delete" onClick={onDelete} />
          </div>
        </div>
      )}
    </li>
  );
}
