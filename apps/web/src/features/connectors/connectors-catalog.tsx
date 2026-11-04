"use client";

import Link from "next/link";
import { useState } from "react";
import type { ConnectorCatalogRow, LibraryItem, Workspace } from "@/data/types";
import { LibraryList } from "@/features/library/library-list";
import { Input } from "@/shared/ui/field";
import { Panel } from "@/shared/ui/panel";

const SHOWN = 16;

const SOURCE: Record<string, string> = {
  hermes: "Hermes's catalog",
  agos: "AGOS",
  google: "Google",
};

/** Settings → Connectors: everything a workspace can connect, in one list. Nothing
 * is signed in here: each workspace turns on what it needs and signs in with its
 * own account in its own Settings → Connectors. */
export function ConnectorsCatalog({
  apps,
  servers,
  workspaces,
}: {
  apps: ConnectorCatalogRow[];
  servers: LibraryItem[];
  workspaces: Workspace[];
}) {
  const [query, setQuery] = useState("");
  const [all, setAll] = useState(false);
  const nameOf = (id: string) =>
    workspaces.find((w) => w.id === id)?.name ?? id;
  const q = query.trim().toLowerCase();
  const hits = apps
    .filter(
      (a) =>
        !q ||
        [a.title, a.name, a.description].some((t) =>
          t.toLowerCase().includes(q),
        ),
    )
    // Apps a workspace uses first, then the available ones, locked ones last.
    .sort(
      (a, b) =>
        Number(b.usedBy.length > 0) - Number(a.usedBy.length > 0) ||
        Number(Boolean(a.locked)) - Number(Boolean(b.locked)),
    );
  const shown = q || all ? hits : hits.slice(0, SHOWN);

  return (
    <div className="flex max-w-4xl flex-col gap-8">
      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h3 className="text-sm font-medium">Apps</h3>
          <Input
            type="search"
            placeholder="Search apps (notion, google, composio…)"
            aria-label="Search apps"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
            }}
            className="h-8 max-w-96 flex-1"
          />
        </div>
        <Panel as="ul" className="divide-y divide-line">
          {shown.map((a) => (
            <li
              key={a.name}
              className="flex flex-wrap items-start gap-x-4 gap-y-1 px-5 py-3"
            >
              <span
                aria-hidden
                className="grid size-9 shrink-0 place-items-center rounded-lg bg-sunken font-display text-sm font-semibold"
              >
                {a.title.slice(0, 1).toUpperCase()}
              </span>
              <span className="min-w-60 flex-1">
                <span className="block font-medium">{a.title}</span>
                <span className="line-clamp-2 block text-sm text-ink-2">
                  {a.locked ?? a.description}
                </span>
                <span className="mt-0.5 inline-block rounded bg-sunken px-1.5 py-0.5 text-xs text-ink-3">
                  {SOURCE[a.source] ?? a.source}
                  {a.login === "oauth" ? " · sign in per workspace" : ""}
                </span>
              </span>
              <UsedIn
                ids={a.usedBy}
                nameOf={nameOf}
                locked={Boolean(a.locked)}
              />
            </li>
          ))}
        </Panel>
        {hits.length === 0 && <p className="text-sm text-ink-3">No match.</p>}
        {!q && !all && hits.length > SHOWN && (
          <button
            type="button"
            className="self-start text-sm text-ink-2 hover:text-ink"
            onClick={() => {
              setAll(true);
            }}
          >
            Show all {hits.length}
          </button>
        )}
      </section>
      <section className="flex flex-col gap-3">
        <div>
          <h3 className="text-sm font-medium">Your MCP servers</h3>
          <p className="mt-1 max-w-2xl text-sm text-ink-2">
            A server you define once (its URL or command, never its key). Each
            workspace adds it from its own Connectors and gives its own key or
            sign-in there. A change here reaches every workspace that added it;
            deleting it removes it from them.
          </p>
        </div>
        <LibraryList
          kind="mcp"
          items={servers}
          workspaces={workspaces}
          catalog={[]}
          noSources
        />
      </section>
    </div>
  );
}

function UsedIn({
  ids,
  nameOf,
  locked,
}: {
  ids: string[];
  nameOf: (id: string) => string;
  locked: boolean;
}) {
  if (locked) return <span className="text-sm text-ink-3">Not available</span>;
  if (ids.length === 0)
    return <span className="text-sm text-ink-3">Not on in any workspace</span>;
  return (
    <span className="text-sm text-ink-3">
      On in{" "}
      {ids.map((id, i) => (
        <span key={id}>
          {i > 0 ? ", " : ""}
          <Link
            href={`/w/${encodeURIComponent(id)}/settings/connectors`}
            className="text-ink-2 underline hover:text-ink"
          >
            {nameOf(id)}
          </Link>
        </span>
      ))}
    </span>
  );
}
