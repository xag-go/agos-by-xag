"use client";

import { useMemo, useState, useTransition } from "react";
import type { ErrorIssue, ErrorIssues } from "@/data/queries";
import { TimeAgo } from "@/shared/time-ago";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { FormStatus } from "@/shared/ui/form-status";
import { DiagnosticsButton } from "./diagnostics-button";
import { markErrorFixed, reopenError } from "./errors-actions";
import { PanelSection } from "@/shared/ui/panel";

const SOURCES = {
  core: "AGOS core",
  web: "Web app",
  hermes: "Hermes",
} as const;

const select =
  "h-8 rounded-md border border-line bg-transparent px-2 text-sm text-ink";

function Issue({
  issue,
  workspace,
  onFixed,
}: {
  issue: ErrorIssue;
  workspace: string;
  onFixed: (id: number) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  const fixed = issue.status === "fixed";

  const change = () =>
    start(async () => {
      const got = await (fixed ? reopenError : markErrorFixed)(issue.id);
      setError(got.error);
      if (!got.error && !fixed) onFixed(issue.id);
    });

  return (
    <li className="flex flex-col gap-2 border-b border-line px-4 py-3 last:border-b-0">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs text-ink-3">
            <span className="font-medium text-ink-2">#{issue.id}</span> ·{" "}
            {SOURCES[issue.source]} · {workspace}
            {issue.route ? <> · {issue.route}</> : null}
          </p>
          <p className="text-sm break-words text-ink">
            {issue.errorType ? (
              <span className="font-medium">{issue.errorType}: </span>
            ) : null}
            {issue.message}
          </p>
          <p className="mt-1 text-xs text-ink-3 tabular-nums">
            <span
              className={cn(
                "rounded-full px-2 py-0.5 font-medium",
                fixed ? "bg-sunken text-ink-2" : "bg-danger/15 text-danger",
              )}
            >
              {issue.count}×
            </span>{" "}
            first <TimeAgo iso={issue.firstSeen} /> (on {issue.firstVersion}) ·
            last <TimeAgo iso={issue.lastSeen} /> (on {issue.version})
            {issue.cameBack ? (
              <span className="text-danger"> · came back</span>
            ) : null}
            {fixed && issue.fixedAt ? (
              <>
                {" "}
                · marked fixed <TimeAgo iso={issue.fixedAt} />
              </>
            ) : null}
            {issue.requestId ? <> · ref {issue.requestId}</> : null}
          </p>
        </div>
        <Button
          variant={fixed ? "ghost" : "secondary"}
          disabled={busy}
          onClick={change}
        >
          {fixed ? "Open again" : busy ? "Marking…" : "Mark fixed"}
        </Button>
      </div>
      <FormStatus error={error} />
      {issue.trace ? (
        <details>
          <summary className="cursor-pointer text-xs text-ink-3 hover:text-ink-2">
            Details
          </summary>
          <pre className="mt-2 max-h-72 overflow-auto rounded-lg bg-sunken p-3 text-xs whitespace-pre-wrap text-ink-2">
            {issue.trace}
          </pre>
        </details>
      ) : null}
    </li>
  );
}

/** Settings → Errors: AGOS's own errors and each workspace's Hermes errors,
 * one row per issue (works with no workspace at all). Mark fixed has an Undo
 * right after; the Co-Founder can do both from a chat too. */
export function ErrorsView({
  data,
  workspaces,
}: {
  data: ErrorIssues;
  workspaces: { id: string; name: string }[];
}) {
  const [status, setStatus] = useState<"open" | "fixed" | "all">("open");
  const [source, setSource] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [undo, setUndo] = useState<number | null>(null);
  const [undoError, setUndoError] = useState<string | null>(null);
  const [busy, start] = useTransition();

  const names = useMemo(
    () => new Map(workspaces.map((w) => [w.id, w.name])),
    [workspaces],
  );
  const nameOf = (id: string | null) =>
    id === null ? "AGOS itself" : (names.get(id) ?? id);
  const shown = data.issues.filter(
    (i) =>
      (status === "all" || i.status === status) &&
      (!source || i.source === source) &&
      (!workspace ||
        (workspace === "-"
          ? i.workspaceId === null
          : i.workspaceId === workspace)),
  );
  const open = data.issues.filter((i) => i.status === "open").length;
  const seen = [
    ...new Set(data.issues.map((i) => i.workspaceId).filter((w) => w !== null)),
  ];

  const takeBack = () =>
    start(async () => {
      if (undo === null) return;
      const got = await reopenError(undo);
      setUndoError(got.error);
      if (!got.error) setUndo(null);
    });

  return (
    <PanelSection
      aria-labelledby="errors-list"
      className="flex max-w-4xl flex-col gap-4 p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 id="errors-list" className="font-medium">
            {open === 0
              ? "No open errors"
              : `${open} open error${open === 1 ? "" : "s"}`}
          </h3>
          <p className="mt-1 text-sm text-ink-2">
            A new error, one that comes back, or one that suddenly happens a lot
            reaches you as Settings → Notifications says (“AGOS hit a new
            error”). Secrets are wiped before anything is kept. Running{" "}
            {data.version}.
          </p>
        </div>
        <DiagnosticsButton />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label="Status"
          className={select}
          value={status}
          onChange={(e) => setStatus(e.target.value as typeof status)}
        >
          <option value="open">Open</option>
          <option value="fixed">Fixed</option>
          <option value="all">All</option>
        </select>
        <select
          aria-label="Source"
          className={select}
          value={source}
          onChange={(e) => setSource(e.target.value)}
        >
          <option value="">Every source</option>
          {Object.entries(SOURCES).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
        <select
          aria-label="Workspace"
          className={select}
          value={workspace}
          onChange={(e) => setWorkspace(e.target.value)}
        >
          <option value="">Every workspace</option>
          <option value="-">AGOS itself</option>
          {[...new Set([...workspaces.map((w) => w.id), ...seen])].map((id) => (
            <option key={id} value={id}>
              {nameOf(id)}
            </option>
          ))}
        </select>
      </div>
      {undo !== null ? (
        <p className="flex flex-wrap items-center gap-2 text-sm text-ink-2">
          Error #{undo} marked fixed.
          <Button variant="ghost" disabled={busy} onClick={takeBack}>
            Undo
          </Button>
        </p>
      ) : null}
      <FormStatus error={undoError} />
      {shown.length === 0 ? (
        <p className="rounded-lg border border-line px-4 py-10 text-center text-sm text-ink-3">
          {data.issues.length === 0
            ? "No errors so far."
            : "No errors match these filters."}
        </p>
      ) : (
        <ul className="overflow-hidden rounded-lg border border-line">
          {shown.map((issue) => (
            <Issue
              key={issue.id}
              issue={issue}
              workspace={nameOf(issue.workspaceId)}
              onFixed={(id) => {
                setUndo(id);
                setUndoError(null);
              }}
            />
          ))}
        </ul>
      )}
    </PanelSection>
  );
}
