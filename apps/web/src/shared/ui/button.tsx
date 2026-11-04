import Link from "next/link";
import type { ComponentProps } from "react";
import { cn } from "./cn";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const base =
  "agos-button inline-flex items-center justify-center gap-2 rounded-lg px-3.5 h-9 text-sm font-medium transition-colors disabled:opacity-50 disabled:pointer-events-none whitespace-nowrap";

const variants: Record<Variant, string> = {
  primary: "bg-accent text-accent-ink hover:opacity-85",
  secondary: "bg-panel text-ink border border-line-strong hover:border-ink-3",
  ghost: "text-ink-2 hover:text-ink hover:bg-sunken",
  danger:
    "bg-panel text-danger border border-line-strong hover:border-danger/50 hover:bg-danger-soft",
};

export function buttonClass(variant: Variant = "secondary", extra?: string) {
  return cn(base, variants[variant], extra);
}

export function Button({
  variant = "secondary",
  className,
  type = "button",
  ...props
}: ComponentProps<"button"> & { variant?: Variant }) {
  return (
    <button
      type={type}
      className={buttonClass(variant, className)}
      {...props}
    />
  );
}

export function ButtonLink({
  variant = "secondary",
  className,
  ...props
}: ComponentProps<typeof Link> & { variant?: Variant }) {
  return <Link className={buttonClass(variant, className)} {...props} />;
}
