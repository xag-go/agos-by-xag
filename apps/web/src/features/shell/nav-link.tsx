"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { cn } from "@/shared/ui/cn";

/** A sidebar link: icon and label; active = soft fill plus a small accent
 * bar on the left. */
export function NavLink({
  href,
  exact = false,
  icon,
  label,
  badge = 0,
  onNavigate,
  children,
}: {
  href: string;
  exact?: boolean;
  icon: ReactNode;
  label: string;
  /** A count at the right edge (0 = none), e.g. what waits in the Inbox. */
  badge?: number;
  onNavigate?: () => void;
  children: ReactNode;
}) {
  const pathname = usePathname();
  const active = exact ? pathname === href : pathname.startsWith(href);
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      aria-label={badge > 0 ? `${label} (${String(badge)} waiting)` : label}
      onClick={onNavigate}
      className={cn(
        "group/item relative flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-sm transition-colors",
        active
          ? "bg-ink/[0.07] font-medium text-ink"
          : "text-ink-2 hover:bg-ink/4.5 hover:text-ink",
      )}
    >
      <ActiveBar active={active} />
      <span
        aria-hidden="true"
        className="relative grid size-5 shrink-0 place-items-center"
      >
        {icon}
      </span>
      <span className="truncate">{children}</span>
      {badge > 0 && (
        <span
          aria-hidden
          className="ml-auto rounded-full bg-attention px-1.5 py-0.5 text-11 leading-none font-semibold text-attention-ink"
        >
          {badge > 99 ? "99+" : badge}
        </span>
      )}
    </Link>
  );
}

/** The small accent bar at the left edge of the active item. */
export function ActiveBar({ active }: { active: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        "absolute top-1/2 -left-3 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-accent transition-[opacity,transform] duration-300",
        active ? "scale-y-100 opacity-100" : "scale-y-0 opacity-0",
      )}
    />
  );
}

/** The name, shown beside an icon in the slim rail on hover or focus. Uses
 * plain :hover (not Tailwind's hover variant, which only applies on devices
 * that report a mouse). */
export function RailTip({
  always = false,
  children,
}: {
  /** Show it whatever the sidebar's state (the workspace rail). */
  always?: boolean;
  children: ReactNode;
}) {
  return (
    <span
      role="tooltip"
      className={cn(
        "pointer-events-none absolute top-1/2 left-full z-40 ml-3 -translate-x-1 -translate-y-1/2 rounded-md bg-ink px-2 py-1 text-xs font-medium whitespace-nowrap text-paper opacity-0 shadow-lg transition-[opacity,transform] duration-150 [:focus-visible>&]:translate-x-0 [:focus-visible>&]:opacity-100 [:hover>&]:translate-x-0 [:hover>&]:opacity-100",
        always ? "block" : "hidden group-data-[rail]/side:block",
      )}
    >
      {children}
    </span>
  );
}
