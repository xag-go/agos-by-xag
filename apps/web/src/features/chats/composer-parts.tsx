"use client";

import { cn } from "@/shared/ui/cn";

export function IconButton({
  label,
  onClick,
  active,
  className,
  children,
}: {
  label: string;
  onClick: () => void;
  active?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className={cn(
        "flex size-9 items-center justify-center rounded-full text-ink-2 hover:bg-canvas hover:text-ink",
        active && "bg-canvas text-ink",
        className,
      )}
    >
      <svg
        viewBox="0 0 20 20"
        className="size-[1.125rem]"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        aria-hidden
      >
        {children}
      </svg>
    </button>
  );
}

export function MenuItem({
  title,
  hint,
  onClick,
}: {
  title: string;
  hint: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className="flex w-full flex-col items-start rounded-xl px-3 py-2 text-left hover:bg-canvas"
    >
      <span className="text-sm text-ink">{title}</span>
      <span className="text-xs text-ink-3">{hint}</span>
    </button>
  );
}

export function Level({ level }: { level: number }) {
  return (
    <span className="flex h-5 items-center gap-[3px]" aria-hidden>
      {[0.5, 0.8, 1, 0.7, 0.9, 0.6, 1, 0.75, 0.55, 0.85].map((f, i) => (
        <span
          key={i}
          className="w-[3px] rounded-full bg-accent transition-[height] duration-75"
          style={{ height: `${String(4 + Math.round(level * f * 16))}px` }}
        />
      ))}
    </span>
  );
}
