"use client";

import type { ModelSelection } from "@agos/core";
import { useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import type {
  CatalogProvider,
  Founder,
  Heartbeat,
  LibraryItem,
  Proposal,
  Scorecards,
  Team,
} from "@/data/types";
import { ProposalCard } from "@/features/inbox/proposal-card";
import { ItemEditor } from "@/features/library/item-editor";
import type { DocChoice } from "@/features/library/library-shared";
import { copyAgentHere, deleteLibraryItem } from "@/features/library/actions";
import { PageActions } from "@/features/workspaces/page-actions";
import { Button, ButtonLink } from "@/shared/ui/button";
import { useAsk } from "@/shared/ui/confirm";
import { DialogCloseButton, Modal } from "@/shared/ui/dialog";
import { FormStatus } from "@/shared/ui/form-status";
import { PlusIcon } from "@/shared/ui/icons";
import { Tabs } from "@/shared/ui/tabs";
import { AgentRevisions } from "@/features/templates/agent-revisions";
import { suggestKits } from "./actions";
import { FounderPanel } from "./founder-box";
import {
  besideFounder,
  buildTree,
  layout,
  type Copyable,
  type Node,
} from "./hierarchy-layout";
import { Chart } from "./hierarchy-chart";
import { AgentCard } from "./agent-card";
import { Notice, SuggestHiresDialog } from "./suggest-hires-dialog";

/**
 * The team as an org chart you can pan and zoom: the Co-Founder on top, the
 * members under it, each a compact box (who, role, model, a dot for its
 * state), joined by lines. A click on a box opens its card: what it does,
 * Message, Edit (the agent's form in a popup) and Delete. New agents come from
 * the page title's buttons; another project never sees them, and a copy from
 * another project becomes this team's own.
 */
export function Hierarchy({
  workspaceId,
  workspaceName,
  team,
  cofounderModel,
  agents,
  pending = [],
  copyable,
  catalog,
  docFiles = [],
  heartbeats = [],
  hiresCard = null,
  scorecards = null,
  founder = null,
}: {
  workspaceId: string;
  /** Under the Co-Founder's box (every other box shows its @name). */
  workspaceName: string;
  team: Team;
  cofounderModel: ModelSelection | null;
  agents: LibraryItem[];
  /** Hires waiting for the owner (the Inbox's), shown in their future place. */
  pending?: Proposal[];
  copyable: Copyable[];
  catalog: CatalogProvider[];
  docFiles?: DocChoice[];
  /** Each member's heartbeat and the Co-Founder's (agent ""), read once with the page. */
  heartbeats?: Heartbeat[];
  /** The owner's "Suggest hires" card still open on the Co-Founder (Hermes's Kanban). */
  hiresCard?: string | null;
  /** This week's scorecards (derived from Hermes's board; Step 63). */
  scorecards?: Scorecards | null;
  /** The owner himself, beside the Co-Founder (his tasks on Hermes's Kanban). */
  founder?: Founder | null;
}) {
  const router = useRouter();
  const [editing, setEditing] = useState<LibraryItem | "new" | null>(null);
  const [selected, setSelected] = useState<Node | null>(null);
  const [showFounder, setShowFounder] = useState(false);
  const [copying, setCopying] = useState(false);
  const [asking, setAsking] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  const { dialog, confirm } = useAsk();

  const root = useMemo<Node>(
    () => buildTree(team, agents, pending, cofounderModel, catalog),
    [team, agents, pending, cofounderModel, catalog],
  );
  const teammates = useMemo(
    () => agents.map((a) => ({ name: a.name, title: a.title })),
    [agents],
  );

  const { placed, width, height, founderAt } = useMemo(
    () => besideFounder(layout(root), founder !== null),
    [root, founder],
  );
  const cards = useMemo(
    () => new Map((scorecards?.members ?? []).map((c) => [c.member, c])),
    [scorecards],
  );
  // Members without a whole kit (hired before kits, or one missing a part) that
  // no card is on yet: "Suggest kits for all" asks for each, one at a time.
  const kitless = team.members.filter(
    (m) => m.kit && m.kit !== "whole" && !m.kitCard,
  ).length;

  function remove(agent: LibraryItem) {
    void (async () => {
      const ok = await confirm({
        title: `Delete “${agent.title}”?`,
        body: "It leaves this team for good. Its past messages stay.",
        confirmLabel: "Delete",
        danger: true,
      });
      if (!ok) return;
      setSelected(null);
      start(async () => {
        const r = await deleteLibraryItem(agent.id, workspaceId);
        if (r.error) setError(r.error);
      });
    })();
  }

  return (
    <div data-fill className="relative flex min-h-0 flex-1 flex-col">
      {dialog}
      <PageActions>
        {copyable.length > 0 && (
          <Button
            variant="ghost"
            onClick={() => {
              setCopying((v) => !v);
            }}
          >
            Copy from another project
          </Button>
        )}
        {hiresCard ? (
          <ButtonLink
            variant="ghost"
            href={`/w/${workspaceId}/kanban?card=${encodeURIComponent(hiresCard)}`}
            title="The Co-Founder is working on your last ask; its suggestions arrive in your Inbox."
          >
            Hires asked — see the card
          </ButtonLink>
        ) : (
          <Button
            variant="ghost"
            onClick={() => {
              setCopying(false);
              setAsking(true);
            }}
          >
            Suggest hires
          </Button>
        )}
        {kitless > 1 && (
          <Button
            variant="ghost"
            disabled={busy}
            title="The Co-Founder proposes a whole kit for each member that has none (or one missing a part), one after the other. Each arrives in your Inbox to edit and approve."
            onClick={() => {
              setError(null);
              start(async () => {
                const r = await suggestKits(workspaceId);
                if (r.error) setError(r.error);
                else
                  setNotice(
                    `Asked the Co-Founder for ${String(r.asked ?? 0)} kit${r.asked === 1 ? "" : "s"} — they arrive in your Inbox one by one` +
                      (r.left
                        ? ` (${String(r.left)} more on the next ask)`
                        : ""),
                  );
              });
            }}
          >
            Suggest kits for all ({kitless})
          </Button>
        )}
        <Button
          variant="primary"
          onClick={() => {
            setCopying(false);
            setEditing("new");
          }}
        >
          <PlusIcon />
          Create agent
        </Button>
      </PageActions>

      <Chart
        placed={placed}
        width={width}
        height={height}
        workspaceName={workspaceName}
        cards={cards}
        onPick={setSelected}
        founder={founder}
        founderAt={founderAt}
        onPickFounder={() => {
          setShowFounder(true);
        }}
      />
      {agents.length === 0 && pending.length === 0 && (
        <p className="pointer-events-none absolute inset-x-0 bottom-8 text-center text-sm text-ink-3">
          No members yet. Create this project&apos;s agents with the button
          above, or ask the Co-Founder in a chat.
        </p>
      )}
      {error && (
        <div className="absolute bottom-4 left-4">
          <FormStatus error={error} />
        </div>
      )}

      {copying && (
        <Modal
          label="Copy an agent from another project"
          onClose={() => {
            setCopying(false);
          }}
        >
          <div className="flex flex-col gap-3 p-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 className="font-display text-lg font-semibold">
                  Copy from another project
                </h3>
                <p className="mt-1 text-sm text-ink-2">
                  The copy becomes this team&apos;s own. The original stays in
                  its project, untouched.
                </p>
              </div>
              <DialogCloseButton />
            </div>
            <ul className="flex flex-col divide-y divide-line">
              {copyable.map((c) => (
                <li
                  key={c.id}
                  className="flex items-center justify-between gap-4 py-2"
                >
                  <span className="text-sm">
                    {c.title}{" "}
                    <span className="text-ink-3">· {c.workspace}</span>
                  </span>
                  <Button
                    className="h-8"
                    disabled={busy}
                    onClick={() => {
                      start(async () => {
                        const r = await copyAgentHere(workspaceId, c.id);
                        if (r.error) setError(r.error);
                        else setCopying(false);
                      });
                    }}
                  >
                    Copy here
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        </Modal>
      )}

      {selected?.pending && editing === null && (
        <Modal
          label={selected.pending.label}
          onClose={() => {
            setSelected(null);
          }}
        >
          <div className="p-6">
            <div className="mb-3 flex items-start justify-between gap-3">
              <p className="text-sm text-ink-2">
                A hire waiting for you. Approve to create this member here, in
                this place of the team; Revise sends your note back; Reject
                closes it.
              </p>
              <DialogCloseButton />
            </div>
            <ProposalCard
              workspaceId={workspaceId}
              proposal={selected.pending}
              onDecided={() => {
                setSelected(null);
                router.refresh();
              }}
            />
          </div>
        </Modal>
      )}

      {selected && !selected.pending && editing === null && (
        <Modal
          label={selected.worker.title}
          onClose={() => {
            setSelected(null);
          }}
        >
          <AgentCard
            node={selected}
            workspaceId={workspaceId}
            workspaceName={workspaceName}
            teammates={teammates}
            busy={busy}
            heartbeat={heartbeats.find(
              (h) => h.agent === (selected.worker.name ?? ""),
            )}
            scorecard={cards.get(selected.worker.name || "cofounder")}
            week={scorecards?.week ?? ""}
            onEdit={
              selected.agent
                ? () => {
                    setEditing(selected.agent);
                    setSelected(null);
                  }
                : undefined
            }
            onDelete={
              selected.agent
                ? () => {
                    remove(selected.agent as LibraryItem);
                  }
                : undefined
            }
          />
        </Modal>
      )}

      {editing !== null && (
        <Modal
          label={editing === "new" ? "New agent" : `Edit ${editing.title}`}
          size="lg"
          onClose={() => {
            setEditing(null);
          }}
        >
          {editing === "new" ? (
            <ItemEditor
              key="new"
              kind="agent"
              item={null}
              catalog={catalog}
              workspaceId={workspaceId}
              docFiles={docFiles}
              teammates={teammates}
              frameless
              onDone={() => {
                setEditing(null);
              }}
            />
          ) : (
            <Tabs
              items={[
                {
                  id: "settings",
                  label: "Settings",
                  content: (
                    <ItemEditor
                      key={editing.id}
                      kind="agent"
                      item={editing}
                      catalog={catalog}
                      workspaceId={workspaceId}
                      docFiles={docFiles}
                      teammates={teammates}
                      frameless
                      onDone={() => {
                        setEditing(null);
                      }}
                    />
                  ),
                },
                {
                  id: "revisions",
                  label: "Revisions",
                  content: (
                    <AgentRevisions
                      workspaceId={workspaceId}
                      agentId={editing.id}
                    />
                  ),
                },
              ]}
            />
          )}
        </Modal>
      )}

      {showFounder && founder && (
        <Modal
          label={founder.name || founder.title}
          onClose={() => {
            setShowFounder(false);
          }}
        >
          <FounderPanel workspaceId={workspaceId} founder={founder} />
        </Modal>
      )}

      {asking && (
        <SuggestHiresDialog
          workspaceId={workspaceId}
          onClose={() => {
            setAsking(false);
          }}
          onAsked={(words) => {
            setAsking(false);
            setNotice(words);
            router.refresh();
          }}
        />
      )}
      {notice && <Notice words={notice} onGone={setNotice} />}
    </div>
  );
}
