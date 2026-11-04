import { cn } from "@/shared/ui/cn";
import { PANEL } from "@/shared/ui/panel";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${String(bytes)} B`;
  if (bytes < 1024 * 1024) return `${String(Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function FileChip({
  href,
  name,
  size,
}: {
  href: string | null;
  name: string;
  size: number;
}) {
  const inner = (
    <>
      <span className="flex size-8 items-center justify-center rounded-lg bg-accent-soft text-accent">
        <svg
          viewBox="0 0 16 16"
          className="size-4"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.4}
          aria-hidden
        >
          <path
            d="M9 1.75H4.5A1.75 1.75 0 0 0 2.75 3.5v9c0 .97.78 1.75 1.75 1.75h7c.97 0 1.75-.78 1.75-1.75V5.5L9 1.75Z"
            strokeLinejoin="round"
          />
          <path d="M9 1.75V5.5h3.75" strokeLinejoin="round" />
        </svg>
      </span>
      <span className="flex min-w-0 flex-col">
        <span className="truncate text-sm text-ink">{name}</span>
        <span className="text-xs text-ink-3">{formatSize(size)}</span>
      </span>
    </>
  );
  const cls = cn(PANEL, "flex max-w-72 items-center gap-2.5 px-2.5 py-2");
  return href ? (
    <a href={href} className={cn(cls, "hover:border-line-strong")}>
      {inner}
    </a>
  ) : (
    <div className={cls}>{inner}</div>
  );
}
