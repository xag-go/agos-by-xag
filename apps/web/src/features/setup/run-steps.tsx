import Link from "next/link";
import type { AutomationCost, RunDetail, RunStep } from "@/data/types";
import { cn } from "@/shared/ui/cn";
import { formatWhen } from "@/shared/format";
import {
  costText,
  durationText,
  tokenSplit,
  tokensText,
  usageText,
} from "./run-usage";

const STEP: Record<RunStep["status"], { label: string; className: string }> = {
  done: { label: "Done", className: "bg-success-soft text-success" },
  running: { label: "Running", className: "bg-live/15 text-ink" },
  waiting: { label: "Waiting", className: "bg-sunken text-ink-2" },
  skipped: { label: "Skipped", className: "bg-sunken text-ink-3" },
  failed: { label: "Failed", className: "bg-danger-soft text-danger" },
  needs_you: {
    label: "Needs you",
    className: "bg-attention text-attention-ink",
  },
  stopped: { label: "Stopped", className: "bg-danger-soft text-danger" },
};

/** A run step by step, folded under one line (its time, tokens and cost):
 * who worked each step, who was skipped and why, how long, how many tokens. */
export function RunSteps({
  workspaceId,
  detail,
}: {
  workspaceId: string;
  detail: RunDetail | null | undefined;
}) {
  if (!detail) return null;
  return (
    <details className="group mt-2 text-sm">
      <summary className="cursor-pointer list-none text-xs text-ink-2 hover:text-ink">
        <span className="mr-1 inline-block transition-transform group-open:rotate-90">
          ›
        </span>
        {detail.steps.length === 1
          ? "1 step"
          : `${String(detail.steps.length)} steps`}
        {" · "}
        {durationText(detail.durationS)} · {usageText(detail.totals)}
      </summary>
      <ol className="mt-2 flex flex-col divide-y divide-line rounded-lg border border-line">
        {detail.steps.map((step) => (
          <StepRow key={step.key} workspaceId={workspaceId} step={step} />
        ))}
      </ol>
      <p className="mt-1.5 text-xs text-ink-3 tabular-nums">
        Total: {tokenSplit(detail.totals)} · {costText(detail.totals)}
      </p>
    </details>
  );
}

function StepRow({
  workspaceId,
  step,
}: {
  workspaceId: string;
  step: RunStep;
}) {
  const status = STEP[step.status];
  const usage = step.usage;
  return (
    <li className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-3 py-2">
      <span className="min-w-40 flex-1">
        {step.cardId ? (
          <Link
            href={`/w/${encodeURIComponent(workspaceId)}/kanban?card=${encodeURIComponent(step.cardId)}`}
            className="font-medium text-ink hover:text-accent"
          >
            {step.title}
          </Link>
        ) : (
          <span className="font-medium text-ink">{step.title}</span>
        )}
        <span className="text-ink-3"> · {step.agent}</span>
        {step.reason && (
          <span
            className={cn(
              "block text-xs",
              step.status === "failed" ? "text-danger" : "text-ink-2",
            )}
          >
            {step.reason}
          </span>
        )}
      </span>
      <span
        className={cn(
          "rounded-md px-2 py-0.5 text-xs font-medium",
          status.className,
        )}
      >
        {status.label}
      </span>
      <span className="w-40 text-xs text-ink-3 tabular-nums">
        {step.startedAt ? formatWhen(step.startedAt) : "Not started"}
        {" · "}
        {durationText(step.durationS)}
      </span>
      <span
        className="w-44 text-right text-xs text-ink-2 tabular-nums"
        title={tokenSplit(usage)}
      >
        {usageText(usage)}
      </span>
    </li>
  );
}

/** "This month $1.23 · 1.2M tokens", small, for an automation's row. */
export function MonthCost({
  of,
  costs,
}: {
  of: number;
  costs: AutomationCost[];
}) {
  const cost = costs.find((c) => c.automationId === of);
  if (!cost || (cost.thisMonth.runs === 0 && cost.lastMonth.runs === 0)) {
    return null;
  }
  return (
    <p
      className="mt-1 text-xs text-ink-3 tabular-nums"
      title={`Last month: ${usageText(cost.lastMonth.usage)} (${String(cost.lastMonth.runs)} runs)`}
    >
      This month {costText(cost.thisMonth.usage)} ·{" "}
      {tokensText(cost.thisMonth.usage)}
    </p>
  );
}

/** This month and last month, for the automation's Runs. */
export function MonthCosts({
  of,
  costs,
}: {
  of: number;
  costs: AutomationCost[];
}) {
  const cost = costs.find((c) => c.automationId === of);
  if (!cost) return null;
  const rows = [
    ["This month", cost.thisMonth],
    ["Last month", cost.lastMonth],
  ] as const;
  return (
    <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-xs text-ink-2 tabular-nums">
      {rows.map(([label, month]) => (
        <div key={label} className="flex gap-1.5">
          <dt className="text-ink-3">{label}</dt>
          <dd title={tokenSplit(month.usage)}>
            {costText(month.usage)} · {tokensText(month.usage)} ·{" "}
            {month.runs === 1 ? "1 run" : `${String(month.runs)} runs`}
          </dd>
        </div>
      ))}
    </dl>
  );
}
