import Link from "next/link";
import { type ReactNode, Suspense } from "react";
import type {
  AccountLimitView,
  ActivityItem,
  Team,
  Workspace,
} from "@/data/types";
import type { components } from "@/data/core-api";
import { Lamp } from "@/features/channels/lamp";
import { LimitWarnings } from "@/features/settings/limit-warnings";
import { cn } from "@/shared/ui/cn";
import { formatTokens, formatWhen } from "@/shared/format";

type Overview = components["schemas"]["WorkspaceOverview"];

type Counters = {
  working: number;
  waitingForYou: number;
  suggestions: number;
  done: number;
};

/** One project's own dashboard. Everything on it is this workspace only.
 * The overview (usage from Hermes, channels, automations, latest chats) is the
 * slow read: it comes as a promise and its cards stream in behind their own
 * <Suspense>, so the counters, team and activity show without waiting for it. */
export function Dashboard({
  workspace,
  counters,
  limits,
  warnAt = 80,
  activity,
  overview,
  team,
}: {
  workspace: Workspace;
  counters: Counters;
  limits: AccountLimitView[];
  warnAt?: number;
  activity: ActivityItem[];
  overview: Promise<Overview>;
  team: Team;
}) {
  const base = `/w/${workspace.id}`;
  const board = `${base}/kanban`;

  return (
    <div className="dashboard-grid flex min-w-0 flex-col gap-6">
      <LimitWarnings limits={limits} warnAt={warnAt} shared />

      <div className="dashboard-stats grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          label="Waiting for you"
          value={counters.waitingForYou}
          hint={
            counters.waitingForYou > 0 ? "Open the Kanban" : "Nothing to decide"
          }
          href={board}
          tone={counters.waitingForYou > 0 ? "attention" : "plain"}
        />
        <Stat
          label="Working now"
          value={counters.working}
          hint={counters.working > 0 ? "Cards in progress" : "No card running"}
          href={board}
          tone={counters.working > 0 ? "live" : "plain"}
        />
        <Stat
          label="To do"
          value={counters.suggestions}
          hint="Cards not started yet"
          href={board}
        />
        <Stat
          label="Done"
          value={counters.done}
          hint={
            <Suspense fallback={<HintLoading />}>
              <FromOverview overview={overview}>
                {(o) => `${String(o.doneThisWeek)} this week`}
              </FromOverview>
            </Suspense>
          }
          href={board}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,3fr)]">
        <div className="dashboard-grid flex min-w-0 flex-col gap-6">
          <TeamCard team={team} base={base} />
          <Suspense fallback={<CardLoading title="Latest conversations" />}>
            <FromOverview overview={overview}>
              {(o) => <ConversationsCard chats={o.recentChats} base={base} />}
            </FromOverview>
          </Suspense>
          <ActivityCard activity={activity} board={board} />
        </div>
        <div className="dashboard-grid flex min-w-0 flex-col gap-6">
          <Suspense fallback={<CardLoading title={usageTitle()} />}>
            <FromOverview overview={overview}>
              {(o) => <UsageCard usage={o.usage} />}
            </FromOverview>
          </Suspense>
          <Suspense fallback={<CardLoading title="Channels" />}>
            <FromOverview overview={overview}>
              {(o) => <ChannelsCard channels={o.channels} base={base} />}
            </FromOverview>
          </Suspense>
          <Suspense fallback={<CardLoading title="Automations" />}>
            <FromOverview overview={overview}>
              {(o) => (
                <AutomationsCard automations={o.automations} base={base} />
              )}
            </FromOverview>
          </Suspense>
        </div>
      </div>
    </div>
  );
}

function Card({
  title,
  action,
  children,
}: {
  title: string;
  action?: { label: string; href: string };
  children: ReactNode;
}) {
  return (
    <section className="dashboard-panel flex min-w-0 flex-col rounded-xl border border-line bg-panel">
      <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-3.5">
        <h2 className="font-display text-sm font-semibold text-ink">{title}</h2>
        {action && (
          <Link
            href={action.href}
            className="text-xs text-ink-3 transition-colors hover:text-accent"
          >
            {action.label} →
          </Link>
        )}
      </header>
      <div className="px-5 py-4">{children}</div>
    </section>
  );
}

/** Waits for the overview inside the caller's <Suspense> (one read shared by
 * every card that shows a part of it). */
async function FromOverview({
  overview,
  children,
}: {
  overview: Promise<Overview>;
  children: (overview: Overview) => ReactNode;
}) {
  return children(await overview);
}

/** A card's frame with its title while its data is on the way. */
function CardLoading({ title }: { title: string }) {
  return (
    <Card title={title}>
      <div
        role="status"
        aria-label="Loading"
        className="flex animate-pulse flex-col gap-2.5 motion-reduce:animate-none"
      >
        <div className="h-4 w-2/3 rounded bg-sunken" />
        <div className="h-4 w-1/2 rounded bg-sunken" />
        <div className="h-4 w-3/5 rounded bg-sunken" />
      </div>
    </Card>
  );
}

function HintLoading() {
  return (
    <span className="inline-block h-3 w-16 animate-pulse rounded bg-sunken align-middle motion-reduce:animate-none" />
  );
}

function usageTitle(): string {
  return `Usage · ${new Date().toLocaleString("en-GB", { month: "long" })}`;
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="text-sm text-ink-3">{children}</p>;
}

function LiveDot() {
  return (
    <span className="relative inline-flex size-2 shrink-0">
      <span className="absolute inline-flex size-full animate-ping rounded-full bg-live opacity-60" />
      <span className="relative inline-flex size-2 rounded-full bg-live" />
    </span>
  );
}

function Stat({
  label,
  value,
  hint,
  href,
  tone = "plain",
}: {
  label: string;
  value: number;
  hint: ReactNode;
  href: string;
  tone?: "plain" | "attention" | "live";
}) {
  return (
    <Link
      href={href}
      className={cn(
        "dashboard-stat flex min-w-0 flex-col gap-2 rounded-xl border px-5 py-5 transition-colors",
        tone === "attention"
          ? "border-transparent bg-attention text-attention-ink hover:opacity-90"
          : "border-line bg-panel hover:border-line-strong",
      )}
    >
      <span
        className={cn(
          "flex items-center gap-2 text-sm",
          tone === "attention" ? "opacity-80" : "text-ink-2",
        )}
      >
        {tone === "live" && <LiveDot />}
        {label}
      </span>
      <span className="font-display text-4xl leading-none font-semibold tabular-nums">
        {value}
      </span>
      <span
        className={cn(
          "text-xs",
          tone === "attention" ? "opacity-75" : "text-ink-3",
        )}
      >
        {hint}
      </span>
    </Link>
  );
}

function TeamCard({ team, base }: { team: Team; base: string }) {
  const people = [team.cofounder, ...team.members];
  return (
    <Card
      title="Team"
      action={{ label: "Hierarchy", href: `${base}/hierarchy` }}
    >
      <ul className="-my-1 flex flex-col">
        {people.map((w) => (
          <li key={w.name ?? "cofounder"}>
            <Link
              href={
                w.dmChatId
                  ? `${base}/messages?c=${w.dmChatId}`
                  : `${base}/hierarchy`
              }
              className="-mx-2 flex items-center gap-3 rounded-xl px-2 py-2 transition-colors hover:bg-sunken"
            >
              <span
                className={cn(
                  "grid size-9 shrink-0 place-items-center rounded-full text-sm font-semibold",
                  w.name === null
                    ? "bg-accent text-accent-ink"
                    : "bg-sunken text-ink-2",
                )}
              >
                {w.title.slice(0, 1).toUpperCase()}
              </span>
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate text-sm font-medium text-ink">
                  {w.title}
                </span>
                <span className="truncate text-xs text-ink-3">{w.role}</span>
              </span>
              {w.working ? (
                <span className="flex shrink-0 items-center gap-1.5 text-xs text-ink-2">
                  <LiveDot />
                  Working
                </span>
              ) : (
                <span className="shrink-0 text-xs text-ink-3">Idle</span>
              )}
            </Link>
          </li>
        ))}
      </ul>
      {team.members.length === 0 && (
        <p className="mt-3 text-xs text-ink-3">
          Only the Co-Founder for now. Add agents in{" "}
          <Link
            href={`${base}/hierarchy`}
            className="text-accent hover:underline"
          >
            Hierarchy
          </Link>{" "}
          or ask the Co-Founder in a chat.
        </p>
      )}
    </Card>
  );
}

function ConversationsCard({
  chats,
  base,
}: {
  chats: Overview["recentChats"];
  base: string;
}) {
  return (
    <Card
      title="Latest conversations"
      action={{ label: "Team Chat", href: `${base}/messages` }}
    >
      {chats.length === 0 ? (
        <Empty>
          No conversation yet. Say hello to the Co-Founder in Messages.
        </Empty>
      ) : (
        <ul className="-my-1 flex flex-col divide-y divide-line">
          {chats.map((c) => (
            <li key={c.id}>
              <Link
                href={c.href}
                className="group flex flex-col gap-0.5 py-2.5"
              >
                <span className="flex items-baseline justify-between gap-3">
                  <span className="truncate text-sm font-medium text-ink group-hover:text-accent">
                    {c.title}
                  </span>
                  <time className="shrink-0 text-xs text-ink-3" dateTime={c.at}>
                    {formatWhen(c.at)}
                  </time>
                </span>
                <span className="line-clamp-1 text-xs text-ink-3">
                  {c.preview || "—"}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function ActivityCard({
  activity,
  board,
}: {
  activity: ActivityItem[];
  board: string;
}) {
  const items = activity.slice(0, 8);
  return (
    <Card title="Kanban activity" action={{ label: "Kanban", href: board }}>
      {items.length === 0 ? (
        <Empty>
          No card has moved yet. Create a card on the Kanban to get started.
        </Empty>
      ) : (
        <ol className="-my-1 flex flex-col">
          {items.map((a) => (
            <li key={a.id} className="flex gap-3 py-1.5 text-sm">
              <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-line-strong" />
              <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">
                <span className="text-ink">{a.text}</span>
              </span>
              <time className="shrink-0 text-xs text-ink-3" dateTime={a.at}>
                {formatWhen(a.at)}
              </time>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

function UsageCard({ usage }: { usage: Overview["usage"] }) {
  const max = Math.max(1, ...usage.days.map((d) => d.tokens));
  const models = usage.models.filter((m) => m.model);
  return (
    <Card title={usageTitle()}>
      <div className="flex flex-col gap-4">
        <div className="flex items-end justify-between gap-3">
          <div>
            <p className="font-display text-3xl leading-none font-semibold tabular-nums">
              {formatTokens(usage.tokens)}
            </p>
            <p className="mt-1.5 text-xs text-ink-3">
              tokens · {usage.replies}{" "}
              {usage.replies === 1 ? "model call" : "model calls"}
            </p>
          </div>
          <div className="text-right text-xs text-ink-3 tabular-nums">
            <p>new {formatTokens(usage.inputTokens)}</p>
            <p>cached {formatTokens(usage.cachedTokens)}</p>
            <p>out {formatTokens(usage.outputTokens)}</p>
          </div>
        </div>

        <div>
          <div
            className="flex h-16 items-end gap-[3px]"
            role="img"
            aria-label="Tokens per day, last 30 days"
          >
            {usage.days.map((d) => (
              <span
                key={d.day}
                title={`${d.day}: ${formatTokens(d.tokens)} tokens, ${d.replies} model calls`}
                className={cn(
                  "flex-1 rounded-sm",
                  d.tokens > 0 ? "bg-accent" : "bg-sunken",
                )}
                style={{
                  height:
                    d.tokens > 0
                      ? `${Math.max(8, (d.tokens / max) * 100)}%`
                      : "3px",
                }}
              />
            ))}
          </div>
          <div className="mt-1.5 flex justify-between text-11 text-ink-3">
            <span>30 days ago</span>
            <span>Today</span>
          </div>
        </div>

        {models.length > 0 && (
          <ul className="flex flex-col gap-1.5 border-t border-line pt-3">
            {models.map((m) => (
              <li
                key={m.provider + m.model}
                className="flex items-baseline justify-between gap-3 text-sm"
              >
                <span className="truncate text-ink-2">{m.model}</span>
                <span className="shrink-0 text-xs text-ink-3 tabular-nums">
                  {formatTokens(m.tokens)} · {m.replies}
                </span>
              </li>
            ))}
          </ul>
        )}
        <p className="text-11 text-ink-3">This project only.</p>
      </div>
    </Card>
  );
}

function ChannelsCard({
  channels,
  base,
}: {
  channels: Overview["channels"];
  base: string;
}) {
  const href = `${base}/settings/channels`;
  return (
    <Card
      title="Channels"
      action={{ label: channels.length ? "Manage" : "Connect", href }}
    >
      {channels.length === 0 ? (
        <Empty>
          No channel yet.{" "}
          <Link href={href} className="text-accent hover:underline">
            Connect Telegram
          </Link>{" "}
          to talk to this project from your phone.
        </Empty>
      ) : (
        <ul className="-my-1 flex flex-col divide-y divide-line">
          {channels.map((c) => (
            <li key={c.id} className="flex items-center gap-3 py-2.5">
              <Lamp status={c.status} reason={c.reason} />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate text-sm font-medium text-ink">
                  {c.identity ? `@${c.identity.replace(/^@/, "")}` : c.name}
                </span>
                <span className="truncate text-xs text-ink-3">
                  <span className="capitalize">{c.kind}</span>
                  {" · "}
                  {c.status === "connected"
                    ? "Connected"
                    : c.status === "connecting"
                      ? "Connecting…"
                      : `Not connected${c.reason ? `: ${c.reason}` : ""}`}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function AutomationsCard({
  automations,
  base,
}: {
  automations: Overview["automations"];
  base: string;
}) {
  const href = `${base}/automations`;
  const shown = automations.slice(0, 5);
  return (
    <Card title="Automations" action={{ label: "All", href }}>
      {shown.length === 0 ? (
        <Empty>
          None yet. Ask the Co-Founder in a chat, or{" "}
          <Link href={href} className="text-accent hover:underline">
            create one
          </Link>
          .
        </Empty>
      ) : (
        <ul className="-my-1 flex flex-col divide-y divide-line">
          {shown.map((a) => (
            <li
              key={a.id}
              className="flex items-center justify-between gap-3 py-2.5"
            >
              <span className="flex min-w-0 items-center gap-2">
                <span
                  className={cn(
                    "size-1.5 shrink-0 rounded-full",
                    a.state === "error" ||
                      (a.enabled && a.lastResult === "failed")
                      ? "bg-danger"
                      : !a.enabled ||
                          a.state === "paused" ||
                          a.state === "completed"
                        ? "bg-line-strong"
                        : "bg-success",
                  )}
                />
                <span className="truncate text-sm text-ink">{a.name}</span>
              </span>
              <span className="shrink-0 text-xs text-ink-3">
                {a.state === "error"
                  ? "Hermes can't schedule it"
                  : a.state === "completed"
                    ? "Done"
                    : a.state === "paused" && a.enabled
                      ? "Paused"
                      : !a.enabled
                        ? "Off"
                        : a.nextRunAt
                          ? `Next ${formatWhen(a.nextRunAt)}`
                          : a.event
                            ? "When something happens"
                            : "On"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
