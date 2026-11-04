"use client";

import { useEffect, useState, useTransition } from "react";
import type { AgentRevision } from "@/data/types";
import { formatWhen } from "@/shared/format";
import { Button } from "@/shared/ui/button";
import { FormStatus } from "@/shared/ui/form-status";
import { agentRevisions, restoreAgentRevision } from "./actions";

const WHO: Record<string, string> = {
  owner: "you",
  cofounder: "Co-Founder",
  import: "an import",
  template: "a ready-made team",
  hermes: "outside AGOS",
  earlier: "before revisions",
};

/** A member's Revisions tab: every version of who it is (role text, notes,
 * title, model, skills, lead, heartbeat), newest first, each with its diff;
 * Restore writes that version again as a new revision. Read when opened. */
export function AgentRevisions({
  workspaceId,
  agentId,
}: {
  workspaceId: string;
  agentId: number;
}) {
  const [revisions, setRevisions] = useState<AgentRevision[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  const load = () =>
    agentRevisions(workspaceId, agentId).then((r) => {
      if (r.error) setError(r.error);
      setRevisions(r.revisions ?? []);
    });
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- read once per member
  }, [workspaceId, agentId]);

  if (revisions === null)
    return <p className="p-5 text-sm text-ink-3">Loading the revisions…</p>;
  return (
    <ol className="flex flex-col gap-3 p-5">
      <FormStatus error={error} />
      {revisions.length === 0 && (
        <li className="text-sm text-ink-3">No versions kept yet.</li>
      )}
      {revisions.map((rev, i) => (
        <li key={rev.n} className="rounded-xl border border-line bg-panel p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-ink-3">v{rev.n}</span>
            <span className="text-sm font-medium">{rev.summary}</span>
            <span className="text-xs text-ink-3">
              · {WHO[rev.who] ?? rev.who}
              {rev.why ? ` (${rev.why})` : ""} · {formatWhen(rev.at)}
            </span>
            {i > 0 && (
              <Button
                className="ml-auto h-8"
                disabled={busy}
                onClick={() => {
                  setError(null);
                  start(async () => {
                    const r = await restoreAgentRevision(
                      workspaceId,
                      agentId,
                      rev.n,
                    );
                    if (r.error) setError(r.error);
                    else await load();
                  });
                }}
              >
                Restore
              </Button>
            )}
          </div>
          {(rev.changes ?? []).length > 0 && (
            <ul className="mt-2 flex flex-col gap-1.5 text-xs">
              {(rev.changes ?? []).map((c) => (
                <li key={c.field} className="grid grid-cols-[7rem_1fr] gap-2">
                  <span className="text-ink-3">
                    {c.field.replace("_", " ")}
                  </span>
                  {c.lines ? (
                    <pre className="max-h-48 overflow-auto rounded-lg bg-sunken p-2 font-mono text-11 leading-snug whitespace-pre-wrap">
                      {c.lines
                        .split("\n")
                        .slice(2)
                        .map((line, k) => (
                          <span
                            key={k}
                            className={
                              line.startsWith("+")
                                ? "block text-success"
                                : line.startsWith("-")
                                  ? "block text-danger"
                                  : "block text-ink-3"
                            }
                          >
                            {line}
                          </span>
                        ))}
                    </pre>
                  ) : (
                    <span className="min-w-0 break-words">
                      <span className="text-danger line-through">
                        {c.before}
                      </span>{" "}
                      <span className="text-success">{c.after}</span>
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ol>
  );
}
