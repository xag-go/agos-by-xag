"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import type {
  Connector,
  LibraryItem,
  LibraryKind,
  ListFolder,
  WorkspaceApp,
} from "@/data/types";
import { FolderList } from "@/features/folders/folder-list";
import { MoveToFolder } from "@/features/folders/folder-move";
import { ItemActions, UpdateButton } from "@/features/library/item-actions";
import { ItemEditor } from "@/features/library/item-editor";
import { LibrarySources } from "@/features/library/library-sources";
import { ConnectorsHub } from "@/features/connectors/workspace-apps";
import { setConnector } from "@/features/library/actions";
import { Button } from "@/shared/ui/button";
import { FormStatus } from "@/shared/ui/form-status";
import { Modal } from "@/shared/ui/dialog";
import { Switch } from "@/shared/ui/switch";
import { ConnectorConfig, kindLabels } from "./connector-config";
import { Panel } from "@/shared/ui/panel";

// Plugins come later (they can't be isolated); Connectors = apps with an account.
const ORDER: LibraryKind[] = ["skill", "agent", "tool"];

type SkillUpdate = { itemId: number; hasUpdate: boolean; detail: string };

/** What this workspace has: its own skills, agents and connectors, Hermes's tools. */
export function ConnectorsList({
  workspaceId,
  connectors,
  apps,
  mcp,
  skills,
  skillUpdates = [],
  skillFolders = [],
}: {
  workspaceId: string;
  connectors: Connector[];
  apps: WorkspaceApp[];
  mcp: LibraryItem[];
  /** This workspace's own skills (its Co-Founder and every agent read them). */
  skills: LibraryItem[];
  skillUpdates?: SkillUpdate[];
  /** The owner's folders of the Skills list (AGOS's own grouping, no file moves). */
  skillFolders?: ListFolder[];
}) {
  return (
    <div className="flex flex-col gap-8">
      {ORDER.map((kind) => {
        const list = connectors.filter((c) => c.kind === kind);
        if (kind === "skill")
          return (
            <SkillsSection
              key={kind}
              workspaceId={workspaceId}
              connectors={list}
              skills={skills}
              updates={skillUpdates}
              folders={skillFolders}
            />
          );
        return (
          <section
            key={kind}
            aria-labelledby={`kind-${kind}`}
            className="flex flex-col gap-2"
          >
            <h2
              id={`kind-${kind}`}
              className="font-display text-base font-semibold"
            >
              {kindLabels[kind].title}
            </h2>
            {list.length === 0 ? (
              <p className="text-sm text-ink-3">{kindLabels[kind].empty}</p>
            ) : (
              <Panel as="ul" className="divide-y divide-line">
                {list.map((c) => (
                  <ConnectorRow
                    key={c.itemId}
                    workspaceId={workspaceId}
                    connector={c}
                  />
                ))}
              </Panel>
            )}
          </section>
        );
      })}
      <AppsSection
        workspaceId={workspaceId}
        apps={apps}
        servers={connectors.filter((c) => c.kind === "mcp")}
        mcp={mcp}
      />
      <p className="text-xs text-ink-3">
        Changes apply from the agent&apos;s next session or task run.
      </p>
    </div>
  );
}

function ConnectorRow({
  workspaceId,
  connector: c,
  item,
  onEdit,
  update,
  inFolders = false,
}: {
  workspaceId: string;
  connector: Connector;
  /** This workspace's own skill or MCP server: editable and deletable here. */
  item?: LibraryItem;
  onEdit?: (item: LibraryItem) => void;
  /** A newer copy of this skill (Hermes's hub, this machine). */
  update?: SkillUpdate;
  /** A row of a folder list (Skills): the list gives its <li> and a “Move” menu. */
  inFolders?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [, start] = useTransition();
  const canConfigure = !c.locked && c.kind !== "tool";
  const Row = inFolders ? "div" : "li";
  return (
    <Row className={inFolders ? undefined : "px-5 py-3.5"}>
      <div className="grid items-center gap-x-6 gap-y-1 sm:grid-cols-[12rem_1fr_auto_auto]">
        <span className="font-medium">{c.title}</span>
        <span className="text-sm text-ink-2">
          {c.locked ?? c.summary}
          {update?.hasUpdate && (
            <span className="mt-1 flex flex-wrap items-center gap-2 text-xs text-ink-3">
              {update.detail}
              <UpdateButton itemId={c.itemId} workspaceId={workspaceId} />
            </span>
          )}
          {c.kind === "tool" && c.works === false && (
            <span className="mt-0.5 block text-xs font-medium text-attention">
              On, but not working yet: set up its service in Settings → Tools.
            </span>
          )}
          {c.kind === "tool" && c.works === true && (
            <span className="mt-0.5 block text-xs text-success">Working</span>
          )}
          {c.kind === "mcp" && c.needsSecret && (
            <span className="block text-xs text-ink-3">
              {c.secret ? `Credential ${c.secret}` : "No credential yet"}
            </span>
          )}
        </span>
        {canConfigure ? (
          <span className="flex items-center gap-3">
            {inFolders && <MoveToFolder item={c.itemId} />}
            <button
              type="button"
              className="text-sm text-ink-2 hover:text-ink"
              onClick={() => {
                setOpen((o) => !o);
              }}
            >
              {open ? "Close" : "Configure"}
            </button>
          </span>
        ) : inFolders ? (
          <MoveToFolder item={c.itemId} />
        ) : (
          <span />
        )}
        {c.always ? (
          <span className="text-xs text-ink-3">Always on</span>
        ) : (
          <Switch
            defaultOn={c.on}
            disabled={Boolean(c.locked)}
            label={`${c.title} on or off`}
            onChange={(on) => {
              setError(null);
              start(async () => {
                const result = await setConnector(
                  workspaceId,
                  c.itemId,
                  on,
                  c.allowedTools,
                  c.local,
                );
                if (result.error) setError(result.error);
              });
            }}
          />
        )}
      </div>
      <FormStatus error={error} className="mt-1" />
      {open && (
        <>
          <ConnectorConfig workspaceId={workspaceId} connector={c} />
          {item && onEdit && (
            <div className="mt-2 flex flex-wrap gap-3 text-sm">
              <button
                type="button"
                className="text-ink-2 hover:text-ink"
                onClick={() => {
                  onEdit(item);
                }}
              >
                {c.kind === "skill" ? "Edit skill" : "Edit server"}
              </button>
              {c.kind === "skill" && (
                <Link
                  href={`/w/${encodeURIComponent(workspaceId)}/settings/capabilities/skills/${item.id}`}
                  className="text-ink-2 hover:text-ink"
                >
                  Versions &amp; tests
                </Link>
              )}
              {item.source.startsWith("template:") && (
                <span className="text-ink-3">
                  In your list (Settings → Connectors): a change reaches every
                  workspace that added it. Its key and sign-in stay this
                  workspace&apos;s.
                </span>
              )}
              <ItemActions
                item={item}
                nameOf={(id) => id}
                workspaceId={workspaceId}
              />
            </div>
          )}
        </>
      )}
    </Row>
  );
}

/** This workspace's own skills: one copy its Co-Founder and every agent read (a
 * Co-Founder's change reaches the whole team). Made, added, changed and deleted
 * here only; on or off like any capability. */
function SkillsSection({
  workspaceId,
  connectors,
  skills,
  updates,
  folders,
}: {
  workspaceId: string;
  connectors: Connector[];
  skills: LibraryItem[];
  updates: SkillUpdate[];
  folders: ListFolder[];
}) {
  const [editing, setEditing] = useState<LibraryItem | "new" | null>(null);
  return (
    <section aria-labelledby="kind-skill" className="flex flex-col gap-2">
      <h2 id="kind-skill" className="font-display text-base font-semibold">
        {kindLabels.skill.title}
      </h2>
      <p className="max-w-2xl text-sm text-ink-2">
        This workspace&apos;s own. The Co-Founder and every agent here read the
        same copy, so a change the Co-Founder makes reaches the whole team.
        Other workspaces never see them.
      </p>
      <FolderList
        workspaceId={workspaceId}
        kind="skill"
        noun="skill"
        folders={folders}
        rowClassName="px-5 py-3.5"
        empty={<p className="text-sm text-ink-3">{kindLabels.skill.empty}</p>}
        entries={connectors.map((c) => ({
          id: c.itemId,
          text: `${c.title} ${c.name} ${c.summary}`,
          node: (
            <ConnectorRow
              workspaceId={workspaceId}
              connector={c}
              item={skills.find((s) => s.id === c.itemId)}
              onEdit={setEditing}
              update={updates.find((u) => u.itemId === c.itemId)}
              inFolders
            />
          ),
        }))}
      />
      {editing === null && (
        <div className="flex flex-col gap-3">
          <Button
            className="self-start"
            onClick={() => {
              setEditing("new");
            }}
          >
            Create skill
          </Button>
          <LibrarySources kind="skill" workspaceId={workspaceId} />
        </div>
      )}
      {editing !== null && (
        <Modal
          label={editing === "new" ? "New skill" : `Edit ${editing.title}`}
          size="lg"
          onClose={() => {
            setEditing(null);
          }}
        >
          <ItemEditor
            key={editing === "new" ? "new" : editing.id}
            kind="skill"
            item={editing === "new" ? null : editing}
            catalog={[]}
            workspaceId={workspaceId}
            frameless
            onDone={() => {
              setEditing(null);
            }}
          />
        </Modal>
      )}
    </section>
  );
}

/** Connectors: everything this workspace connects, in one place (its apps, its
 * Composio apps, its MCP servers), and one search to add more. */
function AppsSection({
  workspaceId,
  apps,
  servers,
  mcp,
}: {
  workspaceId: string;
  apps: WorkspaceApp[];
  servers: Connector[];
  mcp: LibraryItem[];
}) {
  const [editing, setEditing] = useState<LibraryItem | "new" | null>(null);
  return (
    <section aria-labelledby="kind-apps" className="flex flex-col gap-2">
      <h2 id="kind-apps" className="font-display text-base font-semibold">
        Connectors
      </h2>
      <ConnectorsHub
        workspaceId={workspaceId}
        apps={apps}
        servers={servers.map((c) => (
          <ConnectorRow
            key={c.itemId}
            workspaceId={workspaceId}
            connector={c}
            item={mcp.find((m) => m.id === c.itemId)}
            onEdit={setEditing}
          />
        ))}
        onCustomMcp={() => {
          setEditing("new");
        }}
      />
      {editing !== null && (
        <Modal
          label={editing === "new" ? "New MCP server" : `Edit ${editing.title}`}
          size="lg"
          onClose={() => {
            setEditing(null);
          }}
        >
          <ItemEditor
            key={editing === "new" ? "new" : editing.id}
            kind="mcp"
            item={editing === "new" ? null : editing}
            catalog={[]}
            workspaceId={workspaceId}
            onDone={() => {
              setEditing(null);
            }}
          />
        </Modal>
      )}
    </section>
  );
}
