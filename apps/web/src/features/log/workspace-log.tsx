import Link from "next/link";
import type { LogEntry, LogPage } from "@/data/queries";
import { cn } from "@/shared/ui/cn";
import { formatWhen } from "@/shared/format";

const AREA_LABEL: Record<LogEntry["area"], string> = {
  task: "Tasks",
  automation: "Automations",
  webhook: "Webhooks",
  chat: "Chats",
  cofounder: "Co-Founder",
  goal: "Goals",
  status: "Status cards",
  channel: "Channels",
  system: "AGOS",
};

const LEVEL: Record<
  LogEntry["level"],
  { label: string; dot: string; row: string }
> = {
  ok: { label: "Done", dot: "bg-live", row: "" },
  info: { label: "Info", dot: "bg-ink-3", row: "" },
  warn: { label: "Warning", dot: "bg-attention", row: "" },
  error: { label: "Problem", dot: "bg-danger", row: "bg-danger/5" },
};

type Filters = {
  level: string;
  area?: string | undefined;
  q: string;
  actor: string;
  since: string;
  until: string;
};

function href(base: string, now: Filters, change: Partial<Filters>): string {
  const next = { ...now, ...change };
  const params = new URLSearchParams();
  if (next.level !== "all") params.set("level", next.level);
  if (next.area) params.set("area", next.area);
  if (next.q) params.set("q", next.q);
  if (next.actor) params.set("actor", next.actor);
  if (next.since) params.set("since", next.since);
  if (next.until) params.set("until", next.until);
  const query = params.toString();
  return query ? `${base}?${query}` : base;
}

function Chip({
  to,
  active,
  children,
  tone,
}: {
  to: string;
  active: boolean;
  children: React.ReactNode;
  tone?: "danger";
}) {
  return (
    <Link
      href={to}
      scroll={false}
      className={cn(
        "rounded-full border px-3 py-1 text-xs transition-colors",
        active
          ? tone === "danger"
            ? "border-danger bg-danger/15 text-danger"
            : "border-ink bg-ink text-canvas"
          : "border-line text-ink-2 hover:text-ink",
      )}
    >
      {children}
    </Link>
  );
}

function Row({ entry }: { entry: LogEntry }) {
  const level = LEVEL[entry.level];
  const body = (
    <div
      className={cn(
        "grid grid-cols-[7.5rem_1fr] gap-x-4 gap-y-1 px-4 py-3 sm:grid-cols-[7.5rem_7rem_1fr]",
        level.row,
      )}
    >
      <div className="flex items-center gap-2 text-xs text-ink-3 tabular-nums">
        <span
          className={cn("size-2 shrink-0 rounded-full", level.dot)}
          title={level.label}
        />
        {formatWhen(entry.at)}
      </div>
      <div className="hidden flex-col items-start gap-1 text-xs text-ink-3 sm:flex">
        {AREA_LABEL[entry.area]}
        {(entry.level === "error" || entry.level === "warn") && (
          <span
            className={cn(
              "rounded-full px-2 py-0.5 font-medium",
              entry.level === "error"
                ? "bg-danger/15 text-danger"
                : "bg-attention-soft text-ink",
            )}
          >
            {level.label}
          </span>
        )}
      </div>
      <div className="col-start-2 min-w-0 sm:col-start-3">
        <p className="text-xs text-ink-3">
          <span className="font-medium text-ink-2">{entry.actor}</span>
          {" · "}
          {entry.where}
        </p>
        <p className="text-sm break-words text-ink">{entry.text}</p>
        {entry.cause && (
          <p
            className={cn(
              "mt-1 text-sm break-words",
              entry.level === "error" ? "text-danger" : "text-ink-2",
            )}
          >
            <span className="font-medium">Cause: </span>
            {entry.cause}
          </p>
        )}
      </div>
    </div>
  );
  return (
    <li className="border-b border-line last:border-b-0">
      {entry.href ? (
        <Link href={entry.href} className="block hover:bg-sunken">
          {body}
        </Link>
      ) : (
        body
      )}
    </li>
  );
}

/** Everything that happened in the workspace, and every problem with where and why. */
export function WorkspaceLog({
  baseHref,
  page,
  level,
  area,
  q,
  actor,
  since,
  until,
  before,
}: {
  baseHref: string;
  page: LogPage;
  level: "all" | "problems";
  area?: LogEntry["area"];
  q: string;
  actor: string;
  since: string;
  until: string;
  before?: string;
}) {
  const now: Filters = { level, area, q, actor, since, until };
  const last = page.entries.at(-1);
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <p className="max-w-2xl text-sm text-ink-2">
          Everything that happened in this project and who did it: you, the
          Co-Founder, each agent, the automations; tasks, goals, webhooks,
          messages sent to your channels, and every problem, with where it
          happened and why. Click a line to open it.
        </p>
        {page.problems_24h > 0 && (
          <Link
            href={href(baseHref, now, { level: "problems" })}
            className="rounded-full bg-danger/15 px-3 py-1 text-sm font-medium text-danger"
          >
            {page.problems_24h} problem{page.problems_24h === 1 ? "" : "s"} in
            the last 24 h
          </Link>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Chip
          to={href(baseHref, now, { level: "all" })}
          active={level === "all"}
        >
          Everything
        </Chip>
        <Chip
          to={href(baseHref, now, { level: "problems" })}
          active={level === "problems"}
          tone="danger"
        >
          Problems only
        </Chip>
        <span className="mx-1 h-5 w-px bg-line" />
        <Chip to={href(baseHref, now, { area: undefined })} active={!area}>
          All
        </Chip>
        {(Object.keys(AREA_LABEL) as LogEntry["area"][]).map((key) => (
          <Chip
            key={key}
            to={href(baseHref, now, { area: key })}
            active={area === key}
          >
            {AREA_LABEL[key]}
          </Chip>
        ))}
        <form action={baseHref} className="ml-auto flex flex-wrap gap-2">
          {level !== "all" && (
            <input type="hidden" name="level" value={level} />
          )}
          {area && <input type="hidden" name="area" value={area} />}
          {actor && <input type="hidden" name="actor" value={actor} />}
          <input
            type="date"
            name="since"
            defaultValue={since}
            aria-label="From"
            title="From this day"
            className="h-8 rounded-md border border-line bg-transparent px-2 text-sm text-ink"
          />
          <input
            type="date"
            name="until"
            defaultValue={until}
            aria-label="To"
            title="Up to this day"
            className="h-8 rounded-md border border-line bg-transparent px-2 text-sm text-ink"
          />
          <input
            name="q"
            defaultValue={q}
            placeholder="Search the log"
            className="h-8 w-56 rounded-md border border-line bg-transparent px-3 text-sm text-ink placeholder:text-ink-3"
          />
        </form>
      </div>

      {(page.actors ?? []).length > 1 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-ink-3">Who:</span>
          <Chip to={href(baseHref, now, { actor: "" })} active={!actor}>
            Everyone
          </Chip>
          {(page.actors ?? []).map((a) => (
            <Chip
              key={a.key}
              to={href(baseHref, now, { actor: a.key })}
              active={actor === a.key}
            >
              {a.label}
            </Chip>
          ))}
        </div>
      )}

      {page.entries.length === 0 ? (
        <p className="rounded-lg border border-line px-4 py-10 text-center text-sm text-ink-3">
          {level === "problems"
            ? "No problems. Everything went fine."
            : "Nothing here yet."}
        </p>
      ) : (
        <ul className="overflow-hidden rounded-lg border border-line">
          {page.entries.map((entry) => (
            <Row key={entry.id} entry={entry} />
          ))}
        </ul>
      )}

      <div className="flex gap-3 text-sm">
        {before && (
          <Link
            href={href(baseHref, now, {})}
            className="text-ink-2 hover:text-ink"
          >
            ← Newest
          </Link>
        )}
        {page.more && last && (
          <Link
            href={`${href(baseHref, now, {})}${href(baseHref, now, {}).includes("?") ? "&" : "?"}before=${encodeURIComponent(last.at)}`}
            className="text-ink-2 hover:text-ink"
          >
            Older →
          </Link>
        )}
      </div>
    </div>
  );
}
