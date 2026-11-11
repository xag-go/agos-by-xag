import Link from "next/link";
import type {
  Automation,
  AutomationCost,
  CatalogProvider,
  LibraryItem,
  ListFolder,
} from "@/data/types";
import { FolderList } from "@/features/folders/folder-list";
import { MoveToFolder } from "@/features/folders/folder-move";
import { modelLabel } from "@/features/models/model-label";
import { cn } from "@/shared/ui/cn";
import { Switch } from "@/shared/ui/switch";
import { formatWhen } from "@/shared/format";
import { toggleAutomation } from "./actions";
import { RunNowButton } from "./automation-runs";
import { MonthCost } from "./run-steps";
import { describeCron } from "./schedule";
import { DoneByLevels } from "./done-by-levels";

/** What the list's search matches: the name, the schedule and who does it. */
function searchText(
  a: Automation,
  titleOf: (name: string | null | undefined) => string,
) {
  return [
    a.name,
    a.schedule ? describeCron(a.schedule, a.scheduleDisplay) : "",
    titleOf(a.agent),
    ...(a.steps ?? []).map((s) => titleOf(s.agent)),
  ].join(" ");
}

export function AutomationsList({
  workspaceId,
  automations,
  catalog,
  baseHref,
  agents,
  folders,
  costs = [],
}: {
  workspaceId: string;
  automations: Automation[];
  catalog: CatalogProvider[];
  baseHref: string;
  agents: LibraryItem[];
  /** The owner's folders of this list (AGOS's own grouping). */
  folders: ListFolder[];
  /** What each automation's runs used this month (a small figure per row). */
  costs?: AutomationCost[];
}) {
  const titleOf = (name: string | null | undefined) =>
    name
      ? (agents.find((a) => a.name === name)?.title ?? `@${name}`)
      : "Co-Founder";
  return (
    <FolderList
      workspaceId={workspaceId}
      kind="automation"
      noun="automation"
      folders={folders}
      rowClassName="flex flex-wrap items-start gap-x-6 gap-y-3 px-5 py-4"
      empty={
        <p className="rounded-2xl border border-dashed border-line-strong px-5 py-8 text-center text-sm text-ink-2">
          No automations yet. A daily brief or a weekly review is a good first
          one.
        </p>
      }
      entries={automations.map((a) => ({
        id: a.id,
        text: searchText(a, titleOf),
        node: (
          <>
            <div className="min-w-64 flex-1">
              <Link
                href={`${baseHref}?edit=${String(a.id)}`}
                scroll={false}
                className="font-medium text-ink hover:text-accent"
              >
                {a.name}
              </Link>
              <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-sm text-ink-2">
                {a.schedule && (
                  <span>
                    {describeCron(a.schedule, a.scheduleDisplay)}{" "}
                    <code className="rounded bg-sunken px-1 text-xs text-ink-3">
                      {a.schedule}
                    </code>
                  </span>
                )}
                {a.hook && (
                  <span className="rounded-full bg-accent-soft px-2 py-0.5 text-xs">
                    {a.schedule ? "+ " : ""}the moment something happens
                    (webhook
                    {a.hook.signed
                      ? a.hook.secretWaiting
                        ? ", secret not shown yet"
                        : ""
                      : ", unsigned"}
                    )
                  </span>
                )}
                {a.caughtUp && (
                  <span
                    className="rounded-full bg-sunken px-2 py-0.5 text-xs"
                    title={`Catch-up run (missed at ${formatWhen(a.caughtUp)})`}
                  >
                    Caught up
                  </span>
                )}
                {a.checkFirst && (
                  <span className="rounded-full bg-attention-soft px-2 py-0.5 text-xs">
                    Checks with you first
                  </span>
                )}
              </p>
              <p className="mt-1.5 flex flex-wrap items-center gap-1 text-xs text-ink-2">
                <span className="text-ink-3">Done by</span>
                {(a.steps ?? []).length > 0 ? (
                  <DoneByLevels steps={a.steps ?? []} titleOf={titleOf} />
                ) : (
                  <span className="rounded-full bg-sunken px-2 py-0.5">
                    {titleOf(a.agent)}
                  </span>
                )}
              </p>
              {a.notice && (
                <p role="status" className="mt-1 text-xs text-attention-ink">
                  {a.notice}
                </p>
              )}
              <p className="mt-1 text-xs text-ink-3">
                {modelLabel(a.model, catalog)} · {a.file}
              </p>
            </div>
            <div className="min-w-56 flex-1 text-sm">
              {a.lastRun ? (
                <>
                  <p
                    className={cn(
                      a.lastRun.result === "ok"
                        ? "text-success"
                        : "text-danger",
                    )}
                  >
                    {a.lastRun.result === "ok"
                      ? "Last run succeeded"
                      : "Last run failed"}
                    <span className="text-ink-3">
                      {" "}
                      · {formatWhen(a.lastRun.at)}
                    </span>
                  </p>
                  <p className="text-ink-2">{a.lastRun.summary}</p>
                </>
              ) : (
                <p className="text-ink-3">Never run</p>
              )}
              <MonthCost of={a.id} costs={costs} />
              {a.problem ? (
                <p role="alert" className="mt-1 text-xs text-danger">
                  {a.problem}
                </p>
              ) : (
                a.on &&
                a.nextRunAt && (
                  <p className="mt-1 text-xs text-ink-3">
                    Next run {formatWhen(a.nextRunAt)}
                  </p>
                )
              )}
            </div>
            <div className="flex items-center gap-3">
              <MoveToFolder item={a.id} />
              <RunNowButton
                workspaceId={workspaceId}
                automationId={a.id}
                variables={a.variables}
              />
              <Link
                href={`${baseHref}?hook=${String(a.id)}`}
                scroll={false}
                className="text-sm text-ink-2 hover:text-ink"
              >
                Webhook
              </Link>
              <Link
                href={`${baseHref}?runs=${String(a.id)}`}
                scroll={false}
                className="text-sm text-ink-2 hover:text-ink"
              >
                Runs
              </Link>
              <Link
                href={`${baseHref}?edit=${String(a.id)}`}
                scroll={false}
                className="text-sm text-ink-2 hover:text-ink"
              >
                Edit
              </Link>
              <Switch
                defaultOn={a.on}
                label={`${a.name} on or off`}
                onChange={toggleAutomation.bind(null, workspaceId, a.id)}
              />
            </div>
          </>
        ),
      }))}
    />
  );
}
