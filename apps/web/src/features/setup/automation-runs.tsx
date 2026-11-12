"use client";

import { useState, useTransition } from "react";
import type {
  Automation,
  AutomationCost,
  AutomationRun,
  AutomationVariable,
} from "@/data/types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { DialogCloseButton, RouteDialog } from "@/shared/ui/dialog";
import { Input, Select } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { Markdown } from "@/shared/ui/markdown";
import { formatWhen } from "@/shared/format";
import { runAutomationNow } from "./actions";
import { MonthCosts, RunSteps } from "./run-steps";

/** The last runs of one automation: result, report, proposed cards. */
export function AutomationRuns({
  workspaceId,
  automation,
  runs,
  costs = [],
  closeHref,
}: {
  workspaceId: string;
  automation: Automation;
  runs: AutomationRun[];
  /** What the automations' runs used this month and last month. */
  costs?: AutomationCost[];
  closeHref: string;
}) {
  return (
    <RouteDialog
      closeHref={closeHref}
      label={`${automation.name} runs`}
      size="md"
    >
      <div className="flex max-h-[92dvh] flex-col">
        <header className="flex items-start gap-3 border-b border-line px-5 py-4">
          <div className="flex-1">
            <h2 className="font-display text-xl font-semibold">
              {automation.name}
            </h2>
            <p className="mt-0.5 text-sm text-ink-2">
              The last runs, newest first. Proposed cards go to To do only when
              you add them.
            </p>
            <MonthCosts of={automation.id} costs={costs} />
          </div>
          <RunNowButton
            workspaceId={workspaceId}
            automationId={automation.id}
            variables={automation.variables}
          />
          <DialogCloseButton />
        </header>
        <div className="flex flex-col gap-4 overflow-y-auto px-5 py-5">
          {runs.length === 0 ? (
            <p className="text-sm text-ink-3">
              No runs yet. Use Run now, or wait for its schedule.
            </p>
          ) : (
            runs.map((run) => (
              <RunCard key={run.id} workspaceId={workspaceId} run={run} />
            ))
          )}
        </div>
      </div>
    </RouteDialog>
  );
}

function RunCard({
  workspaceId,
  run,
}: {
  workspaceId: string;
  run: AutomationRun;
}) {
  const ok = run.result === "ok";
  return (
    <article className="rounded-xl border border-line bg-panel px-4 py-3">
      <p
        className={cn(
          "text-sm font-medium",
          ok ? "text-success" : "text-danger",
        )}
      >
        {ok ? "Succeeded" : "Failed"}
        <span className="font-normal text-ink-3">
          {" "}
          · {formatWhen(run.finishedAt ?? run.startedAt)}
          {run.caughtUp
            ? ` · Catch-up run (missed at ${formatWhen(run.caughtUp)})`
            : run.source === "manual"
              ? " · started by hand"
              : run.source === "webhook"
                ? " · started by a webhook"
                : " · on schedule"}
        </span>
        {run.caughtUp && (
          <span className="ml-2 rounded-full bg-sunken px-2 py-0.5 text-xs font-normal text-ink-2">
            Caught up
          </span>
        )}
      </p>
      {run.error && <p className="mt-1 text-sm text-danger">{run.error}</p>}
      {run.report && (
        <Markdown text={run.report} className="mt-2 text-sm text-ink" />
      )}
      <RunSteps workspaceId={workspaceId} detail={run.detail} />
      {run.proposals.length > 0 && (
        <ul className="mt-3 flex flex-col gap-2 border-t border-line pt-3">
          {run.proposals.map((p) => (
            <ProposalRow
              key={p.id}
              workspaceId={workspaceId}
              title={p.title}
              description={p.description}
              kanbanCard={p.kanbanCard}
            />
          ))}
        </ul>
      )}
    </article>
  );
}

/** A card the run proposed: it waits on Hermes's Kanban for the owner. */
function ProposalRow({
  workspaceId,
  title,
  description,
  kanbanCard,
}: {
  workspaceId: string;
  title: string;
  description: string;
  kanbanCard: string;
}) {
  return (
    <li className="flex flex-wrap items-center gap-2 text-sm">
      <span className="min-w-0 flex-1" title={description}>
        {title}
      </span>
      <a
        href={`/w/${encodeURIComponent(workspaceId)}/kanban?card=${encodeURIComponent(kanbanCard)}`}
        className="rounded-md bg-success-soft px-2 py-0.5 text-xs text-success"
      >
        On the Kanban · {kanbanCard}
      </a>
    </li>
  );
}

/** Run now. With typed variables, a small form asks their values first (Run now
 * with variables); the defaults are what a scheduled run would use. */
export function RunNowButton({
  workspaceId,
  automationId,
  variables = [],
  className,
}: {
  workspaceId: string;
  automationId: number;
  variables?: AutomationVariable[];
  className?: string;
}) {
  const [busy, start] = useTransition();
  const [asking, setAsking] = useState(false);
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(variables.map((v) => [v.name, v.default ?? ""])),
  );
  const [note, setNote] = useState<{ error: string | null; ok: boolean }>({
    error: null,
    ok: false,
  });
  const run = (given?: Record<string, string>) => {
    setNote({ error: null, ok: false });
    start(async () => {
      const result = await runAutomationNow(workspaceId, automationId, given);
      setNote({ error: result.error, ok: !result.error });
      if (!result.error) setAsking(false);
    });
  };
  return (
    <span className={cn("flex flex-wrap items-center gap-2", className)}>
      <Button
        className="h-8"
        disabled={busy}
        onClick={() => {
          if (variables.length > 0 && !asking) {
            setAsking(true);
            return;
          }
          run(variables.length > 0 ? values : undefined);
        }}
      >
        {busy ? "Starting…" : asking ? "Run with these values" : "Run now"}
      </Button>
      {asking && (
        <span className="flex w-full flex-col gap-2 rounded-xl border border-line bg-panel p-3">
          {variables.map((v) => (
            <label key={v.name} className="flex items-center gap-2 text-sm">
              <span className="w-32 shrink-0 truncate text-ink-2">
                {v.label || v.name}
              </span>
              {v.type === "select" ? (
                <Select
                  value={values[v.name] ?? ""}
                  onChange={(e) =>
                    setValues((all) => ({ ...all, [v.name]: e.target.value }))
                  }
                >
                  {(v.options ?? []).map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </Select>
              ) : v.type === "boolean" ? (
                <Select
                  value={values[v.name] ?? "no"}
                  onChange={(e) =>
                    setValues((all) => ({ ...all, [v.name]: e.target.value }))
                  }
                >
                  <option value="yes">yes</option>
                  <option value="no">no</option>
                </Select>
              ) : (
                <Input
                  type={
                    v.type === "number"
                      ? "number"
                      : v.type === "date"
                        ? "date"
                        : "text"
                  }
                  value={values[v.name] ?? ""}
                  onChange={(e) =>
                    setValues((all) => ({ ...all, [v.name]: e.target.value }))
                  }
                />
              )}
            </label>
          ))}
          <Button
            type="button"
            variant="ghost"
            className="h-8 self-start"
            onClick={() => setAsking(false)}
          >
            Cancel
          </Button>
        </span>
      )}
      <FormStatus
        error={note.error}
        saved={note.ok}
        savedText="Starts within a minute."
        className="text-xs"
      />
    </span>
  );
}
