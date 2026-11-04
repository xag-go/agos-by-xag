"use client";

import Link from "next/link";
import { useEffect, useState, useTransition } from "react";
import type { ChatSearchHit } from "@/data/types";
import { searchChats } from "./actions";

/** Search every chat of this workspace; results link to the chat. */
export function ChatSearch({ workspaceId }: { workspaceId: string }) {
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<{
    q: string;
    hits: ChatSearchHit[];
  } | null>(null);
  const [, start] = useTransition();
  const q = query.trim();
  // Results only show for the text they were found for.
  const hits = q.length >= 2 && found?.q === q ? found.hits : null;

  useEffect(() => {
    if (q.length < 2) return;
    const timer = setTimeout(() => {
      start(async () => {
        setFound({ q, hits: await searchChats(workspaceId, q) });
      });
    }, 250);
    return () => {
      clearTimeout(timer);
    };
  }, [q, workspaceId]);

  return (
    <div className="relative">
      <input
        type="search"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") setQuery("");
        }}
        placeholder="Search sessions"
        aria-label="Search sessions"
        className="h-8 w-full rounded-lg border border-line bg-panel/70 px-2.5 text-sm text-ink placeholder:text-ink-3 focus-visible:border-accent"
      />
      {hits && (
        <div className="absolute top-full right-0 left-0 z-20 mt-1 max-h-80 overflow-y-auto rounded-xl border border-line bg-panel p-1 shadow-lg">
          {hits.length === 0 ? (
            <p className="px-2.5 py-2 text-xs text-ink-3">Nothing found.</p>
          ) : (
            hits.map((h) => (
              <Link
                key={h.messageId}
                href={`/w/${encodeURIComponent(workspaceId)}/sessions?chat=${String(h.chatId)}`}
                onClick={() => {
                  setQuery("");
                }}
                className="flex flex-col rounded-lg px-2.5 py-1.5 hover:bg-sunken"
              >
                <span className="text-xs text-ink-3">
                  {h.chatTitle} · {h.from === "owner" ? "You" : "Agent"}
                </span>
                <span className="line-clamp-2 text-sm text-ink">{h.body}</span>
              </Link>
            ))
          )}
        </div>
      )}
    </div>
  );
}
