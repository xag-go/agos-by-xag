import type { ComponentProps, ReactNode } from "react";
import { cn } from "./cn";

const control =
  "rounded-lg border border-line-strong bg-panel px-3 text-sm text-ink placeholder:text-ink-3 focus-visible:border-accent";

/** Full width unless the caller gives its own width (`w-40`): the plain
 * class join can't drop `w-full`, and Tailwind's order lets it win. */
function width(className: string | undefined): string {
  return className && /(^|\s)w-/.test(className) ? "" : "w-full";
}

export function Field({
  label,
  hint,
  children,
  className,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={cn("flex flex-col gap-1.5", className)}>
      <span className="text-sm font-medium text-ink">{label}</span>
      {children}
      {hint && <span className="text-xs text-ink-3">{hint}</span>}
    </label>
  );
}

export function Input({ className, ...props }: ComponentProps<"input">) {
  return (
    <input
      className={cn(control, width(className), "h-9", className)}
      {...props}
    />
  );
}

export function Textarea({ className, ...props }: ComponentProps<"textarea">) {
  return (
    <textarea
      className={cn(control, width(className), "min-h-24 py-2", className)}
      {...props}
    />
  );
}

export function Select({ className, ...props }: ComponentProps<"select">) {
  return (
    <select
      className={cn(
        control,
        width(className),
        "agos-select h-9 appearance-none pr-8",
        className,
      )}
      {...props}
    />
  );
}
