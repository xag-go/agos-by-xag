"use client";

import { useState } from "react";
import type {
  CatalogProvider,
  LibraryItem,
  LibraryKind,
  Workspace,
} from "@/data/types";
import { Button } from "@/shared/ui/button";
import { LibrarySources } from "./library-sources";
import { ToolService } from "./tool-service";
import { NOUN } from "./library-shared";
import { ItemActions, UpdateButton } from "./item-actions";
import { ItemEditor } from "./item-editor";
import { Panel } from "@/shared/ui/panel";

/** A list of library items: Settings → Tools, or a workspace's own skills / agents / MCP servers. */
export function LibraryList({
  kind,
  items,
  workspaces,
  catalog,
  updates = [],
  workspaceId,
  noSources = false,
}: {
  kind: LibraryKind;
  items: LibraryItem[];
  workspaces: Workspace[];
  catalog: CatalogProvider[];
  updates?: { itemId: number; hasUpdate: boolean; detail: string }[];
  /** A workspace's own items (its skills, MCP servers): made, changed and seen only there. */
  workspaceId?: string;
  /** No "add from Hermes / the web" panel (Settings → Connectors lists those apart). */
  noSources?: boolean;
}) {
  const [editing, setEditing] = useState<LibraryItem | "new" | null>(null);
  const nameOf = (id: string) =>
    workspaces.find((w) => w.id === id)?.name ?? id;
  const noun = NOUN[kind];

  return (
    <div className="flex flex-col gap-4">
      {kind === "tool" && (
        <p className="max-w-2xl text-sm text-ink-2">
          Every tool Hermes has, from Hermes&apos;s own list: anything Hermes
          adds shows up here by itself. Its core is always on; the others are on
          in every workspace (turn one off in that workspace&apos;s
          Capabilities); locked ones reach accounts outside AGOS.
        </p>
      )}
      {items.length === 0 ? (
        <p className="text-sm text-ink-3">No {noun}s yet.</p>
      ) : (
        <Panel as="ul" className="divide-y divide-line">
          {items.map((item) => (
            <li
              key={item.id}
              className="flex flex-wrap items-start gap-x-6 gap-y-2 px-5 py-4"
            >
              <div className="min-w-60 flex-1">
                <p className="font-medium">
                  {item.title}{" "}
                  <span className="font-mono text-xs text-ink-3">
                    {item.name}
                  </span>
                </p>
                <p className="text-sm text-ink-2">
                  {item.locked ?? item.summary}
                </p>
                {kind === "tool" && !item.locked && <ToolService item={item} />}
              </div>
              {!workspaceId && (
                <p className="text-sm text-ink-3">
                  {item.always
                    ? "Always on (Hermes's core)"
                    : item.locked
                      ? "Locked"
                      : item.usedBy.length === 0
                        ? "Not enabled in any workspace"
                        : `Enabled in ${item.usedBy.map(nameOf).join(", ")}`}
                </p>
              )}
              {workspaceId &&
                updates.some((u) => u.itemId === item.id && u.hasUpdate) && (
                  <UpdateButton itemId={item.id} workspaceId={workspaceId} />
                )}
              {kind !== "tool" && (
                <div className="flex gap-3 text-sm">
                  <button
                    type="button"
                    className="text-ink-2 hover:text-ink"
                    onClick={() => {
                      setEditing(item);
                    }}
                  >
                    Edit
                  </button>
                  <ItemActions
                    item={item}
                    nameOf={nameOf}
                    workspaceId={workspaceId}
                  />
                </div>
              )}
            </li>
          ))}
        </Panel>
      )}
      {kind !== "tool" && editing === null && (
        <div className="flex flex-col gap-3">
          <Button
            className="self-start"
            onClick={() => {
              setEditing("new");
            }}
          >
            Create {noun}
          </Button>
          {!noSources && (
            <LibrarySources kind={kind} workspaceId={workspaceId} />
          )}
        </div>
      )}
      {editing !== null && (
        <ItemEditor
          key={editing === "new" ? "new" : editing.id}
          kind={kind}
          item={editing === "new" ? null : editing}
          catalog={catalog}
          workspaceId={workspaceId}
          onDone={() => {
            setEditing(null);
          }}
        />
      )}
    </div>
  );
}
