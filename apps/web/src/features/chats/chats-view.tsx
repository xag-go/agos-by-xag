import Link from "next/link";
import type {
  CatalogProvider,
  ChannelConnection,
  Chat,
  ChatAddress,
} from "@/data/types";
import { cn } from "@/shared/ui/cn";
import { createChat } from "./actions";
import { ChatHeader } from "./chat-header";
import { ChatSearch } from "./chat-search";
import { Conversation } from "./conversation";
import { TimeAgo } from "@/shared/time-ago";
import { Panel } from "@/shared/ui/panel";

export function ChatsView({
  workspaceId,
  chats,
  current,
  asked = false,
  catalog,
  agents = [],
  addresses = [],
  connections = [],
}: {
  workspaceId: string;
  chats: Chat[];
  current: Chat | null;
  /** The URL names a chat. On a phone that opens the chat; otherwise the list. */
  asked?: boolean;
  catalog: CatalogProvider[];
  agents?: { name: string; title: string }[];
  addresses?: ChatAddress[];
  connections?: ChannelConnection[];
}) {
  const base = `/w/${workspaceId}/sessions`;
  // One column on a phone: the list, or (when a chat is asked) the chat with a
  // way back. Both side by side from md up.
  return (
    <Panel
      data-fill
      className="grid min-h-112 flex-1 grid-cols-1 overflow-hidden max-md:grid-rows-1 md:grid-cols-[17rem_minmax(0,1fr)]"
    >
      <nav
        aria-label="Sessions"
        className={cn(
          "min-h-0 flex-col border-b border-line bg-sunken/50 md:flex md:border-r md:border-b-0",
          asked ? "hidden" : "flex",
        )}
      >
        <div className="flex flex-col gap-2 p-2">
          <form
            action={createChat.bind(null, workspaceId)}
            className="flex gap-1.5"
          >
            <input
              name="title"
              aria-label="New session name"
              placeholder="New session — e.g. Research"
              className="h-8 min-w-0 flex-1 rounded-lg border border-line-strong bg-panel px-2.5 text-sm text-ink placeholder:text-ink-3 focus-visible:border-accent max-md:h-11"
            />
            <button
              type="submit"
              aria-label="Add session"
              className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-ink hover:opacity-85 max-md:size-11"
            >
              <svg
                viewBox="0 0 16 16"
                className="size-4"
                fill="none"
                stroke="currentColor"
                strokeWidth={1.75}
                aria-hidden
              >
                <path d="M8 3.5v9M3.5 8h9" strokeLinecap="round" />
              </svg>
            </button>
          </form>
          <ChatSearch workspaceId={workspaceId} />
        </div>
        <ul className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto px-2 pb-2">
          {chats.map((c) => {
            const active = c.id === current?.id;
            return (
              <li key={c.id}>
                <Link
                  href={`${base}?chat=${String(c.id)}`}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex flex-col gap-0.5 rounded-xl px-3 py-2",
                    active ? "bg-ink/[0.07]" : "hover:bg-ink/4.5",
                  )}
                >
                  <span className="flex items-center gap-2">
                    <span
                      className={cn(
                        "truncate text-sm",
                        active ? "font-medium text-ink" : "text-ink",
                      )}
                    >
                      {c.title}
                    </span>
                    {c.working && (
                      <span
                        className="size-1.5 shrink-0 animate-pulse rounded-full bg-accent"
                        aria-label="answering"
                      />
                    )}
                    {c.channel === "telegram" && (
                      <span className="rounded-md bg-accent-soft px-1.5 text-xs text-accent">
                        Telegram
                      </span>
                    )}
                    <span className="ml-auto shrink-0 text-xs text-ink-3">
                      {c.preview ? <TimeAgo iso={c.updatedAt} /> : null}
                    </span>
                  </span>
                  <span className="truncate text-xs text-ink-3">
                    {c.working ? "Answering…" : c.preview || "No messages yet"}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
        <p className="border-t border-line px-4 py-2.5 text-xs text-ink-3">
          Each session keeps its own context and works only inside this
          workspace.
        </p>
      </nav>

      {current ? (
        <section
          aria-label={current.title}
          className={cn(
            "min-h-0 min-w-0 flex-col md:flex",
            asked ? "flex" : "hidden",
          )}
        >
          <ChatHeader
            workspaceId={workspaceId}
            chat={current}
            backHref={base}
            catalog={catalog}
            agents={agents}
            addresses={addresses}
            connections={connections}
          />
          <Conversation
            key={current.id}
            workspaceId={workspaceId}
            chat={current}
          />
        </section>
      ) : (
        <p className="hidden p-6 text-sm text-ink-3 md:block">
          No sessions yet. Name one on the left — e.g. Research, Ads, Taxes.
        </p>
      )}
    </Panel>
  );
}
