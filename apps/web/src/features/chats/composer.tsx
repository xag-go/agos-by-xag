"use client";

import { useEffect, useRef, useState } from "react";
import type { Chat } from "@/data/types";
import { useAppFacts } from "@/shared/app-facts";
import { cn } from "@/shared/ui/cn";
import { useDraft } from "@/shared/use-draft";
import { hermesCommands, type HermesCommand } from "./actions";
import { toBase64 } from "@/shared/files";
import { formatSeconds, useVoiceNote } from "./use-voice-note";
import { IconButton, Level, MenuItem } from "./composer-parts";
import { AccessSwitch } from "./access-switch";
import {
  megabytes,
  mentionAt,
  type Draft,
  type DraftFile,
  type ReplyTarget,
} from "./composer-types";
import { MenuBackdrop } from "@/shared/ui/menu-backdrop";
import { Panel } from "@/shared/ui/panel";

type Props = {
  workspaceId: string;
  chat: Chat;
  busy: boolean;
  sending: boolean;
  stopping: boolean;
  error: string | null;
  onError: (message: string | null) => void;
  onSend: (draft: Draft) => void;
  onStop: () => void;
  /** Answering a precise message: shown above the box, cancelable. */
  replyTo?: ReplyTarget | null;
  onCancelReply?: () => void;
  /** In a group: members you can @mention (name + shown title). */
  mentionable?: { name: string; title: string }[];
  placeholder?: string;
};

/**
 * The message box: text, "+" to add files and screenshots, paste or drop a
 * screenshot straight in, hold a voice note, and the chat's access switch.
 */
export function Composer({
  workspaceId,
  chat,
  busy,
  sending,
  stopping,
  error,
  onError,
  onSend,
  onStop,
  replyTo = null,
  onCancelReply,
  mentionable = [],
  placeholder,
}: Props) {
  // What he was typing stays when he leaves the chat and comes back.
  const { text, setText, clear } = useDraft(
    `${workspaceId}:chat:${String(chat.id)}`,
  );
  const [mention, setMention] = useState<{
    start: number;
    query: string;
  } | null>(null);
  const [pick, setPick] = useState(0);
  // Hermes's own /commands (a chat on Hermes's Telegram): the same list Telegram
  // shows when he types "/", loaded the first time he does.
  const [commands, setCommands] = useState<HermesCommand[] | null>(null);
  const slash = /^\/(\w{0,40})$/.exec(text)?.[1]?.toLowerCase();
  useEffect(() => {
    if (slash === undefined || commands !== null) return;
    let gone = false;
    void hermesCommands(workspaceId, chat.id).then((found) => {
      if (!gone) setCommands(found);
    });
    return () => {
      gone = true;
    };
  }, [slash, commands, workspaceId, chat.id]);
  const commandMatches =
    slash === undefined || !commands
      ? []
      : commands.filter((c) => c.command.startsWith(slash)).slice(0, 8);
  const matches = mention
    ? mentionable
        .filter(
          (m) =>
            m.name.toLowerCase().startsWith(mention.query) ||
            m.title.toLowerCase().includes(mention.query),
        )
        .slice(0, 6)
    : [];
  function choose(name: string) {
    if (!mention) return;
    const el = box.current;
    const caret = el?.selectionStart ?? text.length;
    const next = `${text.slice(0, mention.start)}@${name} ${text.slice(caret)}`;
    setText(next);
    setMention(null);
    requestAnimationFrame(() => {
      const at = mention.start + name.length + 2;
      el?.focus();
      el?.setSelectionRange(at, at);
    });
  }
  const [files, setFiles] = useState<DraftFile[]>([]);
  const [dragging, setDragging] = useState(false);
  const [menu, setMenu] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const imagePicker = useRef<HTMLInputElement>(null);
  const limits = useAppFacts()?.attachments ?? null;
  const imageTypes = new Set(limits?.imageTypes ?? []);
  const recorder = useVoiceNote({
    onDone: (file) => {
      onSend({ text: "", files: [file] });
    },
    onError,
    maxBytes: limits?.maxFileBytes ?? null,
    maxSeconds: limits?.maxVoiceSeconds ?? null,
  });

  // The box grows with the text, up to a limit.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${String(Math.min(el.scrollHeight, 240))}px`;
  }, [text]);

  async function add(list: File[]) {
    onError(null);
    const next = [...files];
    for (const file of list) {
      if (limits && next.length >= limits.maxFiles) {
        onError(`Up to ${String(limits.maxFiles)} attachments per message.`);
        break;
      }
      if (limits && file.size > limits.maxFileBytes) {
        onError(
          `${file.name} is larger than ${megabytes(limits.maxFileBytes)}.`,
        );
        continue;
      }
      if (
        limits &&
        next.reduce((n, f) => n + f.size, 0) + file.size > limits.maxTotalBytes
      ) {
        onError(
          `Attachments are limited to ${megabytes(limits.maxTotalBytes)} per message.`,
        );
        break;
      }
      const mime = file.type || "application/octet-stream";
      const image = imageTypes.has(mime);
      const name =
        file.name && file.name !== "image.png"
          ? file.name
          : `screenshot-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.png`;
      next.push({
        key: `${String(Date.now())}-${String(next.length)}-${name}`,
        kind: image ? "image" : "file",
        name,
        mime,
        size: file.size,
        data: await toBase64(file),
        ...(image ? { preview: URL.createObjectURL(file) } : {}),
      });
    }
    setFiles(next);
    box.current?.focus();
  }

  function remove(key: string) {
    setFiles((list) => {
      const gone = list.find((f) => f.key === key);
      if (gone?.preview) URL.revokeObjectURL(gone.preview);
      return list.filter((f) => f.key !== key);
    });
  }

  const canSend = !sending && (text.trim().length > 0 || files.length > 0);
  function submit() {
    if (!canSend) return;
    onSend({ text, files, ...(replyTo ? { replyTo } : {}) });
    clear();
    setFiles([]);
  }

  return (
    <div className="shrink-0 px-4 pb-4 sm:px-8">
      <div className="w-full">
        {error && (
          <p role="alert" className="mb-2 px-1 text-sm text-danger">
            {error}
          </p>
        )}
        <div
          onDragOver={(e) => {
            if (e.dataTransfer.types.includes("Files")) {
              e.preventDefault();
              setDragging(true);
            }
          }}
          onDragLeave={() => {
            setDragging(false);
          }}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            void add([...e.dataTransfer.files]);
          }}
          className={cn(
            "relative rounded-composer border bg-panel shadow-composer transition-colors focus-within:border-accent/60",
            dragging ? "border-accent bg-accent-soft/40" : "border-line",
          )}
        >
          {dragging && (
            <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-composer text-sm font-medium text-accent">
              Drop to attach
            </div>
          )}
          {replyTo && (
            <div className="mx-3 mt-3 flex items-start gap-2 rounded-2xl border-l-3 border-accent bg-sunken px-3 py-2">
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium text-accent">
                  {replyTo.excerpt
                    ? `Replying to a part of ${replyTo.from}'s message`
                    : `Replying to ${replyTo.from}`}
                </p>
                <p
                  className={cn(
                    "text-sm text-ink-2",
                    replyTo.excerpt ? "line-clamp-3 italic" : "truncate",
                  )}
                >
                  {replyTo.excerpt ? `“${replyTo.excerpt}”` : replyTo.preview}
                </p>
              </div>
              <button
                type="button"
                onClick={onCancelReply}
                aria-label="Cancel the reply"
                className="flex size-6 shrink-0 items-center justify-center rounded-full text-ink-3 hover:bg-panel hover:text-ink"
              >
                <svg viewBox="0 0 12 12" className="size-2.5" aria-hidden>
                  <path
                    d="M3 3l6 6M9 3l-6 6"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                  />
                </svg>
              </button>
            </div>
          )}

          {files.length > 0 && (
            <ul className="flex flex-wrap gap-2 px-4 pt-3">
              {files.map((f) => (
                <li key={f.key} className="group relative">
                  {f.preview ? (
                    // eslint-disable-next-line @next/next/no-img-element -- local blob preview
                    <img
                      src={f.preview}
                      alt={f.name}
                      className="size-16 rounded-xl border border-line object-cover"
                    />
                  ) : (
                    <span className="flex h-16 max-w-44 items-center gap-2 rounded-xl border border-line bg-canvas px-3 text-xs text-ink">
                      <span className="truncate">{f.name}</span>
                    </span>
                  )}
                  <button
                    type="button"
                    aria-label={`Remove ${f.name}`}
                    onClick={() => {
                      remove(f.key);
                    }}
                    className="absolute -top-1.5 -right-1.5 flex size-5 items-center justify-center rounded-full bg-ink text-canvas shadow"
                  >
                    <svg viewBox="0 0 12 12" className="size-2.5" aria-hidden>
                      <path
                        d="M3 3l6 6M9 3l-6 6"
                        stroke="currentColor"
                        strokeWidth="1.6"
                        strokeLinecap="round"
                      />
                    </svg>
                  </button>
                </li>
              ))}
            </ul>
          )}

          {commandMatches.length > 0 && (
            <ul
              role="listbox"
              aria-label="Hermes commands"
              className="mx-2.5 mt-2 flex flex-col overflow-hidden rounded-xl border border-line bg-panel py-1 shadow-lg"
            >
              {commandMatches.map((c, i) => (
                <li key={c.command} role="option" aria-selected={i === pick}>
                  <button
                    type="button"
                    onMouseDown={(e) => {
                      e.preventDefault();
                      setText(`/${c.command} `);
                      box.current?.focus();
                    }}
                    className={cn(
                      "flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm",
                      i === pick ? "bg-sunken text-ink" : "text-ink-2",
                    )}
                  >
                    <span className="font-medium text-ink">/{c.command}</span>
                    <span className="truncate text-ink-3">{c.description}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}

          {matches.length > 0 && (
            <ul
              role="listbox"
              aria-label="Mention a member"
              className="mx-2.5 mt-2 flex flex-col overflow-hidden rounded-xl border border-line bg-panel py-1 shadow-lg"
            >
              {matches.map((m, i) => (
                <li key={m.name} role="option" aria-selected={i === pick}>
                  <button
                    type="button"
                    onMouseDown={(e) => {
                      e.preventDefault();
                      choose(m.name);
                    }}
                    className={cn(
                      "flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm",
                      i === pick ? "bg-sunken text-ink" : "text-ink-2",
                    )}
                  >
                    <span className="font-medium text-ink">@{m.name}</span>
                    <span className="truncate text-ink-3">{m.title}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}

          {recorder.recording ? (
            <div className="flex h-[3.25rem] items-center gap-3 px-5">
              <span className="relative flex size-2.5" aria-hidden>
                <span className="absolute inline-flex size-full animate-ping rounded-full bg-danger/60" />
                <span className="relative inline-flex size-2.5 rounded-full bg-danger" />
              </span>
              <span className="text-sm text-ink tabular-nums">
                {formatSeconds(recorder.seconds)}
              </span>
              <Level level={recorder.level} />
              <span className="text-xs text-ink-3">Recording a voice note</span>
            </div>
          ) : (
            <textarea
              ref={box}
              rows={1}
              value={text}
              placeholder={
                busy
                  ? "Add to the conversation…"
                  : (placeholder ?? "Message the agent…")
              }
              onChange={(e) => {
                setText(e.target.value);
                if (mentionable.length > 0) {
                  setMention(
                    mentionAt(e.target.value, e.target.selectionStart),
                  );
                  setPick(0);
                }
              }}
              onPaste={(e) => {
                const pasted = [...e.clipboardData.files];
                if (pasted.length > 0) {
                  e.preventDefault();
                  void add(pasted);
                }
              }}
              onKeyDown={(e) => {
                if (commandMatches.length > 0) {
                  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                    e.preventDefault();
                    const step = e.key === "ArrowDown" ? 1 : -1;
                    setPick(
                      (p) =>
                        (p + step + commandMatches.length) %
                        commandMatches.length,
                    );
                    return;
                  }
                  if (e.key === "Tab") {
                    e.preventDefault();
                    const c = commandMatches[pick] ?? commandMatches[0];
                    if (c) setText(`/${c.command} `);
                    return;
                  }
                }
                if (matches.length > 0) {
                  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                    e.preventDefault();
                    const step = e.key === "ArrowDown" ? 1 : -1;
                    setPick(
                      (p) => (p + step + matches.length) % matches.length,
                    );
                    return;
                  }
                  if (e.key === "Enter" || e.key === "Tab") {
                    e.preventDefault();
                    choose((matches[pick] ?? matches[0])?.name ?? "");
                    return;
                  }
                  if (e.key === "Escape") {
                    setMention(null);
                    return;
                  }
                }
                if (
                  e.key === "Enter" &&
                  !e.shiftKey &&
                  !e.nativeEvent.isComposing
                ) {
                  e.preventDefault();
                  submit();
                }
              }}
              aria-label="Message"
              className="block max-h-60 min-h-[3.25rem] w-full resize-none bg-transparent px-5 pt-3.5 pb-2 text-body leading-relaxed text-ink outline-none placeholder:text-ink-3"
            />
          )}

          <div className="flex items-center gap-1.5 px-2.5 pb-2.5">
            {recorder.recording ? (
              <button
                type="button"
                onClick={recorder.cancel}
                className="h-9 rounded-full px-3 text-sm text-ink-2 hover:bg-canvas hover:text-ink"
              >
                Cancel
              </button>
            ) : (
              <div className="relative">
                <IconButton
                  label="Add context"
                  active={menu}
                  onClick={() => {
                    setMenu((m) => !m);
                  }}
                >
                  <path d="M10 4.5v11M4.5 10h11" strokeLinecap="round" />
                </IconButton>
                {menu && (
                  <>
                    <MenuBackdrop
                      onClose={() => {
                        setMenu(false);
                      }}
                    />
                    <Panel
                      role="menu"
                      className="absolute bottom-11 left-0 z-30 w-64 p-1.5 shadow-popover"
                    >
                      <MenuItem
                        title="Photos & screenshots"
                        hint="Or paste one with ⌘V"
                        onClick={() => {
                          setMenu(false);
                          imagePicker.current?.click();
                        }}
                      />
                      <MenuItem
                        title="Files"
                        hint="Saved in this workspace for the agent"
                        onClick={() => {
                          setMenu(false);
                          picker.current?.click();
                        }}
                      />
                    </Panel>
                  </>
                )}
              </div>
            )}
            <input
              ref={imagePicker}
              type="file"
              accept="image/png,image/jpeg,image/webp,image/gif"
              multiple
              hidden
              onChange={(e) => {
                void add([...(e.target.files ?? [])]);
                e.target.value = "";
              }}
            />
            <input
              ref={picker}
              type="file"
              multiple
              hidden
              onChange={(e) => {
                void add([...(e.target.files ?? [])]);
                e.target.value = "";
              }}
            />

            {!recorder.recording && (
              <AccessSwitch
                workspaceId={workspaceId}
                chat={chat}
                onError={onError}
              />
            )}

            <div className="ml-auto flex items-center gap-1.5">
              {!recorder.recording && recorder.supported && (
                <IconButton
                  label="Record a voice note"
                  onClick={recorder.start}
                >
                  <rect x="7.25" y="2.75" width="5.5" height="9.5" rx="2.75" />
                  <path
                    d="M4.5 9.5a5.5 5.5 0 0 0 11 0M10 15v2.5"
                    strokeLinecap="round"
                  />
                </IconButton>
              )}
              {busy && !recorder.recording && !canSend ? (
                <button
                  type="button"
                  onClick={onStop}
                  disabled={stopping}
                  aria-label="Stop the answer"
                  className="flex size-9 items-center justify-center rounded-full bg-ink text-canvas hover:opacity-90 disabled:opacity-50"
                >
                  <span className="size-3 rounded-3 bg-current" />
                </button>
              ) : (
                <button
                  type="button"
                  onClick={recorder.recording ? recorder.finish : submit}
                  disabled={recorder.recording ? false : !canSend}
                  aria-label={recorder.recording ? "Send voice note" : "Send"}
                  className="flex size-9 items-center justify-center rounded-full bg-accent text-accent-ink transition-opacity hover:opacity-90 disabled:bg-line disabled:text-ink-3"
                >
                  <svg
                    viewBox="0 0 20 20"
                    className="size-4"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    aria-hidden
                  >
                    <path
                      d="M10 16V4M4.5 9.5 10 4l5.5 5.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </button>
              )}
            </div>
          </div>
        </div>
        <p className="mt-2 px-1 text-center text-caption-sm text-ink-3">
          Enter to send · Shift+Enter for a new line · paste or drop screenshots
        </p>
      </div>
    </div>
  );
}
