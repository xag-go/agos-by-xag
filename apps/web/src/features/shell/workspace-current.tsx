"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { cn } from "@/shared/ui/cn";
import { WrenchIcon } from "@/shared/ui/icons";
import { SidebarCollapseButton } from "./sidebar-shell";

export const lastWorkspaceCookie = "agos-last-ws";

export type SwitcherWorkspace = {
  id: string;
  name: string;
  /** The icon's stamp when the workspace has a picture (shared/ui/workspace-tile). */
  icon?: string | null;
};

/** The workspace you're in, from the address; none on the app's own pages
 * (general Settings, a new workspace). */
export function useCurrentWorkspace(
  workspaces: SwitcherWorkspace[],
): SwitcherWorkspace | null {
  const fromPath = /^\/w\/([^/]+)/.exec(usePathname())?.[1] ?? null;
  return workspaces.find((w) => w.id === fromPath) ?? null;
}

/**
 * Top of the workspace panel: the name of the workspace you're in (switching
 * happens on the rail beside it) and its settings.
 */
export function WorkspaceHeader({
  workspaces,
}: {
  workspaces: SwitcherWorkspace[];
}) {
  const pathname = usePathname();
  const current = useCurrentWorkspace(workspaces);

  // Remember the workspace, so Settings and the home page keep it.
  useEffect(() => {
    if (current && pathname.startsWith(`/w/${current.id}`)) {
      document.cookie = `${lastWorkspaceCookie}=${encodeURIComponent(current.id)}; path=/; max-age=31536000; samesite=lax`;
    }
  }, [current, pathname]);

  if (!current) return null;

  const settingsHref = `/w/${current.id}/settings`;
  const inSettings = pathname.startsWith(settingsHref);
  return (
    <div className="flex h-10 items-center gap-1 pl-2.5">
      <h2
        className="min-w-0 flex-1 truncate font-display text-15 leading-tight font-semibold tracking-tight text-ink"
        title={current.name}
      >
        {current.name}
      </h2>
      <Link
        href={settingsHref}
        aria-label={`${current.name} settings`}
        title="Workspace settings"
        aria-current={inSettings ? "page" : undefined}
        className={cn(
          "grid size-9 shrink-0 place-items-center rounded-lg text-ink-3 transition-colors hover:bg-ink/4.5 hover:text-ink",
          inSettings && "text-ink",
        )}
      >
        <WrenchIcon />
      </Link>
      <SidebarCollapseButton />
    </div>
  );
}
