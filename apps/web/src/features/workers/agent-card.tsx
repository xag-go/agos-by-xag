"use client";

import { useState, useTransition } from "react";
import type { Heartbeat, LibraryItem, Scorecard } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { DialogCloseButton } from "@/shared/ui/dialog";
import { Field, Select } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { PencilIcon, TrashIcon } from "@/shared/ui/icons";
import { Tabs } from "@/shared/ui/tabs";
import { openDm, setReportsTo } from "./actions";
import { ReadinessPanel } from "./readiness";
import { KitChip, SuggestKitButton } from "./kit-chips";
import { HeartbeatField } from "./heartbeat-field";
import { ScorecardPanel } from "./scorecard";
import { STATUS_WORDS, type Node } from "./hierarchy-layout";

/** The card behind a box: who this is, what it does, and what you can do. */
export function AgentCard({
  node,
  workspaceId,
  workspaceName,
  teammates,
  busy,
  heartbeat,
  scorecard,
  week,
  onEdit,
  onDelete,
}: {
  node: Node;
  workspaceId: string;
  workspaceName: string;
  teammates: { name: string; title: string }[];
  busy: boolean;
  heartbeat?: Heartbeat;
  scorecard?: Scorecard;
  week: string;
  onEdit?: () => void;
  onDelete?: () => void;
}) {
  const { worker } = node;
  const def = (node.agent?.definition ?? {}) as { reports_to?: string };
  const [reportsTo, setBoss] = useState(def.reports_to ?? "");
  const [bossError, setBossError] = useState<string | null>(null);
  const [moving, startMove] = useTransition();
  const details = (
    <div className="flex flex-col gap-4 pt-1">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-md bg-sunken px-2 py-0.5 text-xs font-medium text-ink-2">
          {worker.role}
        </span>
        <span className="text-xs text-ink-3">{STATUS_WORDS[node.status]}</span>
      </div>
      {worker.summary && (
        <p className="text-sm leading-relaxed text-ink-2">{worker.summary}</p>
      )}
      {node.org && (
        <div className="flex flex-col gap-1 text-sm">
          <p className="text-ink-2">
            <span className="text-ink-3">Chain of command: </span>
            {[...node.org.chain.map((c) => c.title), "Co-Founder"].join(" → ")}
          </p>
          {node.org.stalled && (
            <p className="text-attention-ink">
              Stalled: {node.org.stalled.words}. Its cards wait until the lead
              moves again, or move it under another lead.
            </p>
          )}
          {node.org.stalls.length > 0 && (
            <p className="text-attention-ink">
              Its team can&apos;t move:{" "}
              {node.org.stalls.map((m) => `@${m}`).join(", ")}
              {node.org.stuckCards > 0 &&
                ` (${String(node.org.stuckCards)} stuck card${node.org.stuckCards === 1 ? "" : "s"})`}
              .
            </p>
          )}
        </div>
      )}
      {node.agent && (
        <Field
          label="Reports to"
          hint="Its place in the org chart. The Co-Founder, or another member (a sub-manager); never a loop."
        >
          <div className="flex items-center gap-2">
            <Select
              value={reportsTo}
              disabled={moving}
              onChange={(e) => {
                const next = e.target.value;
                const before = reportsTo;
                setBoss(next);
                setBossError(null);
                startMove(async () => {
                  const r = await setReportsTo(
                    workspaceId,
                    (node.agent as LibraryItem).id,
                    next,
                  );
                  if (r.error) {
                    setBoss(before);
                    setBossError(r.error);
                  }
                });
              }}
            >
              <option value="">Co-Founder</option>
              {teammates
                .filter((t) => t.name !== worker.name)
                .map((t) => (
                  <option key={t.name} value={t.name}>
                    {t.title} (@{t.name})
                  </option>
                ))}
            </Select>
          </div>
          {bossError && <FormStatus error={bossError} />}
        </Field>
      )}
      <HeartbeatField
        workspaceId={workspaceId}
        agent={worker.name ?? ""}
        heartbeat={heartbeat}
      />
    </div>
  );
  return (
    <div className="flex flex-col gap-4 p-6">
      <div className="flex items-start gap-3.5">
        <span className="relative grid size-12 shrink-0 place-items-center rounded-full bg-sunken font-display text-lg font-semibold text-ink">
          {worker.title.trim().charAt(0).toUpperCase()}
          <span
            aria-hidden
            className={cn(
              "absolute -right-0.5 -bottom-0.5 size-3 rounded-full ring-3 ring-panel",
              worker.working ? "bg-live" : "bg-ink-3/60",
            )}
          />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="font-display text-lg leading-tight font-semibold text-ink">
            {worker.title}
          </h3>
          <p className="mt-0.5 truncate text-sm text-ink-3">
            {worker.name ? `@${worker.name}` : workspaceName}
            {node.model && (
              <span className="font-mono text-xs"> · {node.model}</span>
            )}
          </p>
        </div>
        <DialogCloseButton />
      </div>
      {worker.name && worker.readiness ? (
        <Tabs
          initial={worker.readiness === "ready" ? "details" : "readiness"}
          items={[
            { id: "details", label: "Details", content: details },
            {
              id: "readiness",
              label: "Readiness",
              content: (
                <div className="pt-3">
                  <ReadinessPanel
                    workspaceId={workspaceId}
                    member={worker.name}
                    kitState={worker.kit ?? null}
                    kitCard={worker.kitCard ?? null}
                  />
                </div>
              ),
            },
            {
              id: "scorecard",
              label: "Scorecard",
              content: (
                <div className="pt-3">
                  <ScorecardPanel card={scorecard} week={week} />
                </div>
              ),
            },
          ]}
        />
      ) : worker.name ? (
        <>
          <Tabs
            items={[
              { id: "details", label: "Details", content: details },
              {
                id: "scorecard",
                label: "Scorecard",
                content: (
                  <div className="pt-3">
                    <ScorecardPanel card={scorecard} week={week} />
                  </div>
                ),
              },
            ]}
          />
          {worker.kit === "none" && (
            <div className="flex flex-wrap items-center gap-2 rounded-xl border border-line px-3 py-2">
              <KitChip state="none" />
              <p className="min-w-0 flex-1 text-sm text-ink-2">
                Hired before kits: no tools, docs or first test listed yet.
              </p>
              <SuggestKitButton
                workspaceId={workspaceId}
                member={worker.name}
                card={worker.kitCard ?? null}
              />
            </div>
          )}
          <details className="text-sm text-ink-2">
            <summary className="cursor-pointer text-ink-3 hover:text-ink">
              Readiness (no kit yet)
            </summary>
            <div className="pt-2">
              <ReadinessPanel workspaceId={workspaceId} member={worker.name} />
            </div>
          </details>
        </>
      ) : (
        details
      )}
      <div className="flex flex-wrap items-center gap-2 border-t border-line pt-4">
        <form action={openDm.bind(null, workspaceId, worker.name ?? "")}>
          <Button type="submit" variant="primary">
            Message
          </Button>
        </form>
        {onEdit && (
          <Button onClick={onEdit}>
            <PencilIcon />
            Edit
          </Button>
        )}
        {onDelete && (
          <Button
            variant="ghost"
            disabled={busy}
            className="ml-auto text-danger hover:text-danger"
            onClick={onDelete}
          >
            <TrashIcon />
            Delete
          </Button>
        )}
      </div>
    </div>
  );
}
