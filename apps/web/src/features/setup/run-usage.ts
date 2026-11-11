import type { Usage } from "@/data/types";
import { formatTokens } from "@/shared/format";

/** A cost as the engine priced it: "$0.85"; "cost unknown" when nothing was
 * priced; "$0.85+" when part of the tokens has no price. */
export function costText(usage: Usage): string {
  if (usage.costUsd === null) return "cost unknown";
  const cost = usage.costUsd;
  const shown = cost > 0 && cost < 0.01 ? "<$0.01" : `$${cost.toFixed(2)}`;
  return usage.priced ? shown : `${shown}+`;
}

/** "45s", "3m 20s", "1h 05m"; an em dash when not known. */
export function durationText(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${String(seconds)}s`;
  if (seconds < 3600) {
    const s = seconds % 60;
    const tail = s ? ` ${String(s).padStart(2, "0")}s` : "";
    return `${String(Math.floor(seconds / 60))}m${tail}`;
  }
  const m = Math.floor((seconds % 3600) / 60);
  return `${String(Math.floor(seconds / 3600))}h ${String(m).padStart(2, "0")}m`;
}

/** "1.2M tokens". */
export function tokensText(usage: Usage): string {
  return `${formatTokens(usage.tokens)} tokens`;
}

/** "1.2M tokens · $0.85". */
export function usageText(usage: Usage): string {
  return `${tokensText(usage)} · ${costText(usage)}`;
}

/** "12k in · 3k out · 1.1M cache". */
export function tokenSplit(usage: Usage): string {
  return [
    `${formatTokens(usage.inputTokens)} in`,
    `${formatTokens(usage.outputTokens)} out`,
    `${formatTokens(usage.cacheReadTokens + usage.cacheWriteTokens)} cache`,
  ].join(" · ");
}
