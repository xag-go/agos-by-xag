"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { cn } from "@/shared/ui/cn";
import { GearIcon } from "@/shared/ui/icons";
import { RailTip } from "./nav-link";

/**
 * The bar under the whole sidebar: general Settings and the theme on the right.
 * In the slim state the two stack under the rail, icons only.
 */
export function SidebarFoot({ theme }: { theme: ReactNode }) {
  const inSettings = usePathname().startsWith("/settings");
  return (
    <div className="agos-foot flex shrink-0 items-center gap-0.5 border-t border-line px-2 py-2 group-data-[rail]/side:flex-col group-data-[rail]/side:px-0">
      <div className="min-w-0 flex-1 group-data-[rail]/side:hidden" />
      <Link
        href="/settings"
        aria-label="Settings"
        aria-current={inSettings ? "page" : undefined}
        className={cn(
          "group/item relative grid size-9 shrink-0 place-items-center rounded-lg text-ink-2 transition-colors hover:bg-ink/4.5 hover:text-ink",
          inSettings && "text-ink",
        )}
      >
        <GearIcon />
        <RailTip always>Settings</RailTip>
      </Link>
      {theme}
    </div>
  );
}
