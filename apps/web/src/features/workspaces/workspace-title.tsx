"use client";

import { usePathname } from "next/navigation";
import { CommandPalette } from "@/features/search/command-palette";
import { TAB_SECTIONS } from "./tab-sections";

/** Where a page puts its own buttons, at the title's right (`PageActions`). */
export const PAGE_ACTIONS_SLOT = "workspace-page-actions";

/** The page's own title (the section you're on), the workspace under it. */
export function WorkspaceTitle({
  workspaceId,
  name,
  description,
}: {
  workspaceId: string;
  name: string;
  description: string;
}) {
  const pathname = usePathname();
  const rest = pathname.slice(`/w/${workspaceId}`.length);
  const section =
    rest === "" || rest === "/"
      ? TAB_SECTIONS.dashboard
      : Object.values(TAB_SECTIONS).find(
          (s) => s.path && (rest === s.path || rest.startsWith(`${s.path}/`)),
        );
  const title = rest.startsWith("/settings")
    ? "Settings"
    : (section?.label ?? name);
  return (
    <header className="workspace-heading flex min-w-0 items-end justify-between gap-4">
      <div className="min-w-0">
        <p className="text-xs font-medium tracking-wider text-ink-3 uppercase">
          {name}
        </p>
        <h1 className="font-display text-2xl font-semibold tracking-tight">
          {title}
        </h1>
        {title === TAB_SECTIONS.dashboard?.label && description && (
          <p className="mt-1 text-sm text-ink-2">{description}</p>
        )}
      </div>
      <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
        <div
          id={PAGE_ACTIONS_SLOT}
          className="flex flex-wrap items-center justify-end gap-2"
        />
        <CommandPalette workspaceId={workspaceId} />
      </div>
    </header>
  );
}
