import { cn } from "@/shared/ui/cn";

/** A thin progress bar (a 0..100 percent; null draws an empty track). */
export function Bar({
  pct,
  thin = false,
  soft = false,
  className,
}: {
  pct: number | null;
  thin?: boolean;
  soft?: boolean;
  className?: string;
}) {
  return (
    <span
      aria-hidden
      className={cn(
        "block overflow-hidden rounded-full bg-sunken",
        thin ? "h-1" : "h-1.5",
        className,
      )}
    >
      <span
        className={cn(
          "block h-full rounded-full",
          soft ? "bg-accent/60" : "bg-accent",
        )}
        style={{ width: `${String(Math.max(0, Math.min(100, pct ?? 0)))}%` }}
      />
    </span>
  );
}
