"use client";

import Link from "next/link";
import { useEffect, useRef, useState, useTransition } from "react";
import type {
  CatalogProvider,
  ChannelConnection,
  Chat,
  ChatAddress,
} from "@/data/types";
import { ChatWhere } from "@/features/channels/chat-where";
import { effortLabel, modelLabel } from "@/features/models/model-label";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { deleteChat, renameChat, setChatAgent, setChatModel } from "./actions";
import { withSelection } from "@/features/models/model-picker";

type ChatHeaderProps = {
  workspaceId: string;
  chat: Chat;
  catalog: CatalogProvider[];
  agents?: { name: string; title: string }[];
  addresses?: ChatAddress[];
  connections?: ChannelConnection[];
  /** On a phone the chat is full-screen: a way back to the list (below md only). */
  backHref?: string;
};

/** Title (click to rename), the chat's model (click to change), and a menu. */
export function ChatHeader({
  workspaceId,
  chat,
  catalog,
  agents = [],
  addresses = [],
  connections = [],
  backHref,
}: ChatHeaderProps) {
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();

  return (
    <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-4 py-2.5 sm:px-6">
      <BackLink href={backHref} />
      {editing ? (
        <form
          className="flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const title = String(
              new FormData(e.currentTarget).get("title") ?? "",
            );
            start(async () => {
              const result = await renameChat(workspaceId, chat.id, title);
              if (result.error) setError(result.error);
              else setEditing(false);
            });
          }}
        >
          <input
            name="title"
            defaultValue={chat.title}
            autoFocus
            aria-label="Chat name"
            onKeyDown={(e) => {
              if (e.key === "Escape") setEditing(false);
            }}
            className="h-8 w-52 rounded-lg border border-accent bg-panel px-2.5 font-display font-semibold text-ink"
          />
          <Button type="submit" className="h-8" disabled={busy}>
            Save
          </Button>
        </form>
      ) : (
        <button
          type="button"
          onClick={() => {
            setEditing(true);
          }}
          className="rounded-md font-display font-semibold hover:text-accent"
          title="Rename"
        >
          {chat.title}
        </button>
      )}
      <ModelMenu
        workspaceId={workspaceId}
        chat={chat}
        catalog={catalog}
        onError={setError}
      />
      {chat.kind === "chat" && (agents.length > 0 || chat.agent) && (
        <select
          aria-label="Agent"
          value={chat.agent ?? ""}
          disabled={busy}
          onChange={(e) => {
            const agent = e.target.value;
            start(async () => {
              const result = await setChatAgent(workspaceId, chat.id, agent);
              if (result.error) setError(result.error);
            });
          }}
          className="h-7 rounded-full border border-line bg-panel px-2.5 text-xs text-ink-2 hover:border-line-strong"
        >
          <option value="">Workspace agent</option>
          {agents.map((a) => (
            <option key={a.name} value={a.name}>
              As {a.title}
            </option>
          ))}
          {chat.agent && !agents.some((a) => a.name === chat.agent) && (
            <option value={chat.agent}>{chat.agent} (turned off)</option>
          )}
        </select>
      )}
      <ChatWhere
        workspaceId={workspaceId}
        chatId={chat.id}
        addresses={addresses}
        connections={connections}
      />
      <div className="ml-auto">
        <DeleteChat workspaceId={workspaceId} chat={chat} />
      </div>
      {error && (
        <p role="alert" className="w-full text-xs text-danger">
          {error}
        </p>
      )}
    </header>
  );
}

function ModelMenu({
  workspaceId,
  chat,
  catalog,
  onError,
}: {
  workspaceId: string;
  chat: Chat;
  catalog: CatalogProvider[];
  onError: (e: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, start] = useTransition();
  const ref = useRef<HTMLDivElement>(null);
  const providers = withSelection(catalog, chat.model);
  const provider = providers.find((p) => p.id === chat.model.provider);
  const models =
    provider?.models.filter((m) => m.modes.includes(chat.model.mode)) ?? [];
  const model = models.find((m) => m.id === chat.model.model);

  useEffect(() => {
    if (!open) return;
    function close(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node))
        setOpen(false);
    }
    document.addEventListener("mousedown", close);
    return () => {
      document.removeEventListener("mousedown", close);
    };
  }, [open]);

  function pick(next: typeof chat.model) {
    onError(null);
    start(async () => {
      const result = await setChatModel(workspaceId, chat.id, next);
      if (result.error) onError(result.error);
      else setOpen(false);
    });
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => {
          setOpen(!open);
        }}
        aria-expanded={open}
        className="flex items-center gap-1 rounded-full border border-line px-2.5 py-0.5 text-xs text-ink-2 hover:border-line-strong hover:text-ink"
      >
        {modelLabel(chat.model, catalog)}
        <svg
          viewBox="0 0 16 16"
          className="size-3"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.5}
          aria-hidden
        >
          <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div className="absolute top-full left-0 z-20 mt-1.5 w-72 rounded-xl border border-line bg-panel p-2 shadow-lg">
          <p className="px-1.5 pb-1 text-xs text-ink-3">Model for this chat</p>
          <select
            aria-label="Model"
            value={`${chat.model.provider}|${chat.model.model}`}
            disabled={busy}
            onChange={(e) => {
              const [pid, mid] = e.target.value.split("|");
              const p = providers.find((x) => x.id === pid);
              const m = p?.models.find((x) => x.id === mid);
              const mode = m?.modes.includes(chat.model.mode)
                ? chat.model.mode
                : m?.modes[0];
              if (!p || !m || !mode) return;
              pick({
                provider: p.id,
                mode,
                model: m.id,
                effort: m.efforts.includes(chat.model.effort)
                  ? chat.model.effort
                  : m.defaultEffort,
              });
            }}
            className="h-9 w-full rounded-lg border border-line-strong bg-panel px-2 text-sm"
          >
            {providers.map((p) => (
              <optgroup key={p.id} label={p.label}>
                {p.models.map((m) => (
                  <option key={m.id} value={`${p.id}|${m.id}`}>
                    {m.label}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          {model && model.efforts.length > 1 && (
            <>
              <p className="px-1.5 pt-2.5 pb-1 text-xs text-ink-3">Effort</p>
              <div className="flex flex-wrap gap-1">
                {model.efforts.map((e) => (
                  <button
                    key={e}
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      pick({ ...chat.model, effort: e });
                    }}
                    className={cn(
                      "rounded-md px-2 py-1 text-xs",
                      e === chat.model.effort
                        ? "bg-accent text-accent-ink"
                        : "bg-sunken text-ink-2 hover:text-ink",
                    )}
                  >
                    {effortLabel(e)}
                  </button>
                ))}
              </div>
            </>
          )}
          <p className="px-1.5 pt-2.5 text-xs text-ink-3">
            Applies from the next message. Only models you connected are listed.
          </p>
        </div>
      )}
    </div>
  );
}

function DeleteChat({
  workspaceId,
  chat,
}: {
  workspaceId: string;
  chat: Chat;
}) {
  const [confirm, setConfirm] = useState(false);
  const [busy, start] = useTransition();
  if (!confirm) {
    return (
      <button
        type="button"
        onClick={() => {
          setConfirm(true);
        }}
        className="rounded-md px-2 py-1 text-xs text-ink-3 hover:bg-sunken hover:text-danger"
      >
        Delete
      </button>
    );
  }
  return (
    <span className="flex items-center gap-2 text-xs">
      <span className="text-ink-2">
        Remove “{chat.title}” from the list? The workspace keeps what it learned
        and its files.
      </span>
      <Button
        variant="danger"
        className="h-7 px-2.5 text-xs"
        disabled={busy}
        onClick={() => {
          start(async () => {
            await deleteChat(workspaceId, chat.id, chat.kind);
          });
        }}
      >
        Delete
      </Button>
      <button
        type="button"
        className="text-ink-3 hover:text-ink"
        onClick={() => {
          setConfirm(false);
        }}
      >
        Cancel
      </button>
    </span>
  );
}

/** The phone's way back from a full-screen chat to the list (hidden from md up). */
function BackLink({ href }: { href: string | undefined }) {
  if (!href) return null;
  return (
    <Link
      href={href}
      aria-label="Back to the list"
      className="-ml-2.5 flex size-11 shrink-0 items-center justify-center rounded-full text-ink-2 hover:bg-sunken hover:text-ink md:hidden"
    >
      <svg
        viewBox="0 0 20 20"
        className="size-5"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.75}
        aria-hidden
      >
        <path
          d="M12.5 4.5 7 10l5.5 5.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </Link>
  );
}
