import Link from "next/link";
import type { AccountLimitView } from "@/data/types";

/** One line per account window at or over the owner's warning level. */
export function LimitWarnings({
  limits,
  warnAt = 80,
  shared = false,
}: {
  limits: AccountLimitView[];
  warnAt?: number;
  shared?: boolean;
}) {
  const hits = limits.flatMap((l) =>
    l.windows
      .filter((w) => (w.usedPercent ?? 0) >= warnAt)
      .map((w) => ({
        key: `${l.provider}-${w.label}`,
        account: l.label,
        window: w,
      })),
  );
  return (
    <>
      {hits.map((h) => (
        <div
          key={h.key}
          role="alert"
          className="flex flex-wrap items-center gap-x-2 gap-y-1.5 rounded-xl border border-ink bg-panel px-4 py-3 text-sm text-ink"
        >
          <span
            aria-hidden="true"
            className="grid size-5 shrink-0 place-items-center rounded-full bg-ink text-11 font-bold text-paper"
          >
            !
          </span>
          <p className="min-w-0 flex-1 basis-52 [overflow-wrap:anywhere]">
            <span className="font-medium">{h.account}</span> is at{" "}
            {Math.round(h.window.usedPercent ?? 0)}% of its{" "}
            {h.window.label.toLowerCase()} limit.
            {shared && " This limit is shared by every workspace."}
          </p>
          <Link
            href="/settings/usage"
            className="ml-auto font-medium text-ink underline decoration-line-strong underline-offset-2 hover:decoration-ink"
          >
            Review limits
          </Link>
        </div>
      ))}
    </>
  );
}
