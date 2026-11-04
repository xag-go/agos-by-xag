import { cn } from "@/shared/ui/cn";

/** Round status light: green connected, red error (reason on hover), pulsing while connecting. */
export function Lamp({
  status,
  reason,
  className,
}: {
  status: "connecting" | "connected" | "error";
  reason?: string;
  className?: string;
}) {
  const label =
    status === "connected"
      ? "Connected"
      : status === "connecting"
        ? "Connecting…"
        : `Not connected${reason ? `: ${reason}` : ""}`;
  return (
    <span
      role="img"
      aria-label={label}
      title={label}
      className={cn("relative inline-flex size-2.5 shrink-0", className)}
    >
      {status === "connecting" && (
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-ink-3 opacity-60" />
      )}
      <span
        className={cn(
          "relative inline-flex size-2.5 rounded-full",
          status === "connected"
            ? "bg-live"
            : status === "connecting"
              ? "bg-ink-3"
              : "bg-danger",
        )}
      />
    </span>
  );
}
