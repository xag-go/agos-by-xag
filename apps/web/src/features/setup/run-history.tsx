import Link from "next/link";
import type { AutomationRunGroup } from "@/data/types";
import { cn } from "@/shared/ui/cn";
import { formatWhen } from "@/shared/format";

const STATUS: Record<
  AutomationRunGroup["status"],
  { label: string; className: string }
> = {
  completed: { label: "Completed", className: "bg-success-soft text-success" },
  needs_you: {
    label: "Needs you",
    className: "bg-attention text-attention-ink",
  },
  running: { label: "Running", className: "bg-live/15 text-ink" },
  waiting: { label: "Waiting", className: "bg-sunken text-ink-2" },
  stopped: { label: "Stopped", className: "bg-danger-soft text-danger" },
};

const SOURCE: Record<string, string> = {
  manual: "by hand",
  webhook: "by a webhook",
  schedule: "on schedule",
};

/** The run history: each run of a Kanban automation is its cards (grouped by the
 * run id in their keys); its status comes from the cards. Read once with the page. */
export function RunHistory({
  workspaceId,
  runs,
}: {
  workspaceId: string;
  runs: AutomationRunGroup[];
}) {
  return (
    <section id="runs" className="flex scroll-mt-32 flex-col gap-4">
      <div>
        <h2 className="font-display text-xl font-semibold">Run history</h2>
        <p className="mt-1 max-w-2xl text-sm text-ink-2">
          Each run of a team or webhook automation, newest first, with its cards
          on the Kanban. A run is completed when every card is done, needs you
          when one is blocked, running while one is being worked.
        </p>
      </div>
      {runs.length === 0 ? (
        <p className="text-sm text-ink-3">No runs on the Kanban yet.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {runs.map((run) => {
            const status = STATUS[run.status];
            return (
              <li
                key={`${String(run.automationId)}:${run.runId}`}
                className="rounded-xl border border-line bg-panel px-4 py-3"
              >
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-medium">{run.automationName}</span>
                  <span className="text-ink-3">
                    · {formatWhen(run.startedAt)} ·{" "}
                    {SOURCE[run.source] ?? run.source}
                  </span>
                  <span
                    className={cn(
                      "ml-auto rounded-md px-2 py-0.5 text-xs font-medium",
                      status.className,
                    )}
                  >
                    {status.label}
                  </span>
                </div>
                <ul className="mt-2 flex flex-wrap gap-1.5">
                  {(run.cards ?? []).map((card) => (
                    <li key={card.id}>
                      <Link
                        href={`/w/${encodeURIComponent(workspaceId)}/kanban?card=${encodeURIComponent(card.id)}`}
                        className="inline-flex items-center gap-1.5 rounded-md border border-line px-2 py-0.5 text-xs text-ink-2 hover:border-ink hover:text-ink"
                        title={card.title}
                      >
                        <span className="font-mono">{card.step}</span>
                        <span className="text-ink-3">{card.status}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
