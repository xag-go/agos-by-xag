import Link from "next/link";
import type { SearchPage, SearchResult } from "@/data/types";
import { cn } from "@/shared/ui/cn";

type SearchType = SearchResult["type"];

const TYPE_LABEL: Record<SearchType, string> = {
  card: "Cards",
  comment: "Comments",
  document: "Documents",
  artifact: "Files",
  agent: "Agents",
  goal: "Goals & projects",
  skill: "Skills",
  chat: "Chats",
};

export const SEARCH_TYPES = Object.keys(TYPE_LABEL) as SearchType[];

/** The excerpt with each matched word highlighted (the core gives their places). */
function Highlighted({ text, marks }: { text: string; marks: number[][] }) {
  const parts: React.ReactNode[] = [];
  let at = 0;
  for (const [start = 0, end = 0] of marks) {
    if (start < at || end <= start) continue;
    if (start > at) parts.push(text.slice(at, start));
    parts.push(
      <mark
        key={`${String(start)}-${String(end)}`}
        className="rounded-sm bg-attention-soft px-0.5 text-ink"
      >
        {text.slice(start, end)}
      </mark>,
    );
    at = end;
  }
  if (at < text.length) parts.push(text.slice(at));
  return <>{parts}</>;
}

function href(base: string, q: string, types: SearchType[]): string {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (types.length) params.set("types", types.join(","));
  const query = params.toString();
  return query ? `${base}?${query}` : base;
}

/** The Search page: one box, the kinds as chips (with how many each has), and
 * every match with its excerpt; a click opens the item where it lives. */
export function SearchView({
  baseHref,
  q,
  types,
  page,
}: {
  baseHref: string;
  q: string;
  types: SearchType[];
  page: SearchPage | null;
}) {
  return (
    <div className="flex flex-col gap-5">
      <form action={baseHref} className="flex gap-2">
        {types.length > 0 && (
          <input type="hidden" name="types" value={types.join(",")} />
        )}
        <input
          name="q"
          defaultValue={q}
          autoFocus
          placeholder="Search cards, comments, documents, agents, goals, skills, chats…"
          className="h-10 flex-1 rounded-lg border border-line-strong bg-panel px-3 text-sm text-ink placeholder:text-ink-3 focus-visible:border-accent"
        />
        <button
          type="submit"
          className="h-10 rounded-lg bg-accent px-4 text-sm font-medium text-accent-ink"
        >
          Search
        </button>
      </form>

      <div className="flex flex-wrap items-center gap-2">
        <Link
          href={href(baseHref, q, [])}
          scroll={false}
          className={cn(
            "rounded-full border px-3 py-1 text-xs",
            types.length === 0
              ? "border-ink bg-ink text-canvas"
              : "border-line text-ink-2 hover:text-ink",
          )}
        >
          Everything
        </Link>
        {SEARCH_TYPES.map((t) => {
          const on = types.includes(t);
          const count = page?.counts[t] ?? 0;
          return (
            <Link
              key={t}
              href={href(
                baseHref,
                q,
                on ? types.filter((x) => x !== t) : [...types, t],
              )}
              scroll={false}
              className={cn(
                "rounded-full border px-3 py-1 text-xs",
                on
                  ? "border-ink bg-ink text-canvas"
                  : "border-line text-ink-2 hover:text-ink",
              )}
            >
              {TYPE_LABEL[t]}
              {page && q ? ` · ${String(count)}` : ""}
            </Link>
          );
        })}
        {page && q && (
          <span className="ml-auto text-xs text-ink-3 tabular-nums">
            {String(page.results.length)} shown · {String(page.tookMs)} ms
          </span>
        )}
      </div>

      {!q ? (
        <p className="rounded-lg border border-line px-4 py-10 text-center text-sm text-ink-3">
          Type a few words. Every word must be there (any case); put a phrase in
          &quot;quotes&quot;. Press ⌘K or Ctrl+K anywhere in the workspace to
          search.
        </p>
      ) : page === null ? (
        <p className="rounded-lg border border-line px-4 py-10 text-center text-sm text-danger">
          The search didn&apos;t answer. Try again.
        </p>
      ) : page.results.length === 0 ? (
        <p className="rounded-lg border border-line px-4 py-10 text-center text-sm text-ink-3">
          Nothing found for “{q}”.
        </p>
      ) : (
        <ul className="overflow-hidden rounded-lg border border-line">
          {page.results.map((r) => (
            <li
              key={`${r.type}:${r.id}`}
              className="border-b border-line last:border-b-0"
            >
              <Link
                href={r.href}
                className="flex flex-col gap-1 px-4 py-3 hover:bg-sunken"
              >
                <span className="flex items-center gap-2 text-xs text-ink-3">
                  <span className="rounded-full bg-sunken px-2 py-0.5 font-medium text-ink-2">
                    {TYPE_LABEL[r.type]}
                  </span>
                  {r.where}
                </span>
                <span className="text-sm font-medium text-ink">{r.title}</span>
                {r.excerpt && (
                  <span className="text-sm break-words text-ink-2">
                    <Highlighted text={r.excerpt} marks={r.marks ?? []} />
                  </span>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
