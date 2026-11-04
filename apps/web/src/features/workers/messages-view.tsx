import Link from "next/link";
import type {
  CatalogProvider,
  ChannelConnection,
  Chat,
  ChatAddress,
  Team,
} from "@/data/types";
import { ChatHeader } from "@/features/chats/chat-header";
import { Conversation } from "@/features/chats/conversation";
import { TimeAgo } from "@/shared/time-ago";
import { cn } from "@/shared/ui/cn";
import { openDm } from "./actions";
import { GroupMembers, NewGroup } from "./group-forms";
import { type Shift, ShiftChip } from "./shift-chip";

/**
 * Slack-style: groups (#) and direct messages on the left, the conversation on
 * the right. In a group, @name talks to that member; without a mention the
 * Co-Founder answers or hands it to the member in charge.
 */
export function MessagesView({
  workspaceId,
  team,
  current,
  asked = false,
  catalog,
  addresses = [],
  connections = [],
}: {
  workspaceId: string;
  team: Team;
  current: Chat | null;
  /** The URL names a chat. On a phone that opens it full-screen; otherwise the list. */
  asked?: boolean;
  catalog: CatalogProvider[];
  addresses?: ChatAddress[];
  connections?: ChannelConnection[];
}) {
  const base = `/w/${workspaceId}/messages`;
  const people: Record<string, string> = { "": team.cofounder.title };
  for (const m of team.members) if (m.name) people[m.name] = m.title;
  const dmByAgent = new Map(team.dms.map((c) => [c.agent ?? "", c]));
  const everyone = [team.cofounder, ...team.members];
  const members = team.members.map((m) => ({
    name: m.name ?? "",
    title: m.title,
  }));

  return (
    <div
      data-fill
      className="messages-panel grid min-h-112 flex-1 overflow-hidden rounded-xl border border-line bg-panel max-md:!grid-rows-1 md:grid-cols-[17rem_minmax(0,1fr)]"
    >
      <nav
        aria-label="Conversations"
        className={cn(
          "min-h-0 flex-col gap-4 overflow-y-auto border-b border-line bg-sunken/50 p-2 md:border-r md:border-b-0",
          // One column on a phone: the list, or (when a chat is asked) the
          // chat full-screen with a way back. Both side by side from md up.
          asked ? "hidden md:flex" : "flex",
        )}
      >
        <section className="flex flex-col gap-0.5">
          <div className="flex items-center justify-between px-3 pt-1 pb-1">
            <h2 className="text-xs font-semibold tracking-wide text-ink-3 uppercase">
              Groups
            </h2>
            <NewGroup workspaceId={workspaceId} members={members} />
          </div>
          {team.groups.length === 0 && (
            <p className="px-3 py-1 text-xs text-ink-3">
              No groups yet. Make one with some members.
            </p>
          )}
          {team.groups.map((g) => (
            <Row
              key={g.id}
              href={`${base}?c=${String(g.id)}`}
              active={g.id === current?.id}
              icon="#"
              title={g.title}
              chat={g}
            />
          ))}
        </section>

        <section className="flex flex-col gap-0.5">
          <h2 className="px-3 pt-1 pb-1 text-xs font-semibold tracking-wide text-ink-3 uppercase">
            Direct messages
          </h2>
          {everyone.map((w) => {
            const dm = dmByAgent.get(w.name ?? "");
            return dm ? (
              <Row
                key={w.name ?? ""}
                href={`${base}?c=${String(dm.id)}`}
                active={dm.id === current?.id}
                icon={w.title.slice(0, 1).toUpperCase()}
                title={w.title}
                chat={dm}
                shift={w.shift}
              />
            ) : (
              <form
                key={w.name ?? ""}
                action={openDm.bind(null, workspaceId, w.name ?? "")}
              >
                <button
                  type="submit"
                  className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-sm text-ink-2 hover:bg-ink/4.5 hover:text-ink max-md:min-h-11"
                >
                  <Avatar letter={w.title.slice(0, 1).toUpperCase()} />
                  <span className="truncate">{w.title}</span>
                  {w.shift && <ShiftChip state={w.shift} className="ml-auto" />}
                </button>
              </form>
            );
          })}
        </section>
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
            addresses={addresses}
            connections={connections}
          />
          {current.kind === "group" && (
            <GroupMembers
              workspaceId={workspaceId}
              chatId={current.id}
              current={current.members}
              members={members}
            />
          )}
          <Conversation
            key={current.id}
            workspaceId={workspaceId}
            chat={current}
            people={people}
            mentionable={
              current.kind === "group"
                ? members.filter((m) => current.members.includes(m.name))
                : []
            }
            placeholder={
              current.kind === "group"
                ? "Message the group — @name to talk to one member"
                : `Message ${people[current.agent ?? ""] ?? current.title}…`
            }
          />
        </section>
      ) : (
        <div className="hidden flex-col items-center justify-center gap-2 p-6 text-center md:flex">
          <span className="message-empty-mark" aria-hidden="true">
            ↗
          </span>
          <p className="font-display text-xl font-semibold text-ink">
            Talk to your team
          </p>
          <p className="max-w-sm text-sm text-ink-3">
            Pick someone under Direct messages, or make a group. In a group,
            write @name to talk to one member; without a name, the Co-Founder
            passes it to whoever is in charge.
          </p>
        </div>
      )}
    </div>
  );
}

function Avatar({ letter }: { letter: string }) {
  return (
    <span
      aria-hidden
      className="flex size-6 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-xs font-semibold text-accent"
    >
      {letter}
    </span>
  );
}

function Row({
  href,
  active,
  icon,
  title,
  chat,
  shift,
}: {
  href: string;
  active: boolean;
  icon: string;
  title: string;
  chat: Chat;
  /** A DM's agent under work hours: On / Off / Staying on today. */
  shift?: Shift | null;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center gap-2.5 rounded-xl px-3 py-2",
        active ? "bg-ink/[0.07]" : "hover:bg-ink/4.5",
      )}
    >
      {icon === "#" ? (
        <span aria-hidden className="w-6 text-center font-display text-ink-3">
          #
        </span>
      ) : (
        <Avatar letter={icon} />
      )}
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="flex items-center gap-2">
          <span
            className={cn("truncate text-sm text-ink", active && "font-medium")}
          >
            {title}
          </span>
          {chat.working && (
            <span
              className="size-1.5 shrink-0 animate-pulse rounded-full bg-accent"
              aria-label="answering"
            />
          )}
          {shift && <ShiftChip state={shift} />}
          <span className="ml-auto shrink-0 text-xs text-ink-3">
            {chat.preview ? <TimeAgo iso={chat.updatedAt} /> : null}
          </span>
        </span>
        {chat.preview && (
          <span className="truncate text-xs text-ink-3">{chat.preview}</span>
        )}
      </span>
    </Link>
  );
}
