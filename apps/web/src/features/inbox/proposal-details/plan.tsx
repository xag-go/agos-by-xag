import { cn } from "@/shared/ui/cn";
import { Markdown } from "@/shared/ui/markdown";
import type { PlanPayload } from "../proposal-types";

export function PlanDetails({
  payload: pl,
  compact,
}: {
  payload: PlanPayload;
  compact: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-lg bg-sunken px-3 py-2 text-sm",
        compact ? "max-h-40 overflow-auto" : "max-h-96 overflow-auto",
      )}
    >
      <Markdown text={pl.markdown ?? ""} />
    </div>
  );
}
