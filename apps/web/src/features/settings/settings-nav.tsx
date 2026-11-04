"use client";

import Link from "next/link";
import { Fragment } from "react";
import { usePathname } from "next/navigation";
import { cn } from "@/shared/ui/cn";
import { groupOf, settingsSections } from "./sections";

const groups = settingsSections.map((s) => groupOf(s));

export function SettingsNav() {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Settings sections"
      className="flex gap-1 overflow-x-auto md:sticky md:top-6 md:max-h-[calc(100dvh-3rem)] md:flex-col md:self-start md:overflow-y-auto"
    >
      {settingsSections.map((s, index) => {
        const href = `/settings/${s.slug}`;
        const active = pathname === href;
        const group = groups[index];
        const first = group !== null && groups[index - 1] !== group;
        const last = group !== null && groups[index + 1] !== group;
        return (
          <Fragment key={s.slug}>
            {first && (
              <span className="hidden px-3 pt-3 pb-1 text-xs font-medium tracking-wide text-ink-3 uppercase md:block">
                {group}
              </span>
            )}
            <Link
              href={href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "rounded-lg px-3 py-2 text-sm whitespace-nowrap",
                group && "md:pl-5",
                active
                  ? "bg-ink/[0.07] font-medium text-ink"
                  : "text-ink-2 hover:bg-ink/4.5 hover:text-ink",
              )}
            >
              {s.label}
            </Link>
            {last && <span className="hidden pb-2 md:block" />}
          </Fragment>
        );
      })}
    </nav>
  );
}
