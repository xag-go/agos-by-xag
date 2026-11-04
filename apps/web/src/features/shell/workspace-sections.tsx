"use client";

import type { ReactNode } from "react";
import { TAB_SECTIONS } from "@/features/workspaces/tab-sections";
import {
  ArtifactsIcon,
  AutomationIcon,
  BoardIcon,
  ChatIcon,
  DashboardIcon,
  DocsIcon,
  GoalIcon,
  InboxIcon,
  LogIcon,
  OfficeIcon,
  PeopleIcon,
  ScreenIcon,
  SearchIcon,
  StatusIcon,
  TeamIcon,
} from "@/shared/ui/icons";
import { NavLink } from "./nav-link";
import { useRailPulse } from "./rail-pulse";
import {
  type SwitcherWorkspace,
  useCurrentWorkspace,
} from "./workspace-current";

const ICONS: Record<string, ReactNode> = {
  dashboard: <DashboardIcon />,
  office: <OfficeIcon />,
  board: <BoardIcon />,
  inbox: <InboxIcon />,
  sessions: <ChatIcon />,
  hierarchy: <TeamIcon />,
  vision: <GoalIcon />,
  status: <StatusIcon />,
  messages: <PeopleIcon />,
  automations: <AutomationIcon />,
  docs: <DocsIcon />,
  artifacts: <ArtifactsIcon />,
  screen: <ScreenIcon />,
  log: <LogIcon />,
  search: <SearchIcon />,
};

/** The menu of the workspace you're in (its sections, in the order chosen in
 * Settings → General). */
export function WorkspaceSections({
  workspaces,
  order,
}: {
  workspaces: SwitcherWorkspace[];
  order: string[];
}) {
  const current = useCurrentWorkspace(workspaces);
  if (!current) return null;
  return <SectionLinks workspace={current} order={order} />;
}

/** One workspace's sections as links (the panel, and the rail's preview). */
export function SectionLinks({
  workspace,
  order,
  onNavigate,
}: {
  workspace: SwitcherWorkspace;
  order: string[];
  onNavigate?: () => void;
}) {
  const base = `/w/${workspace.id}`;
  const inbox = useRailPulse()[workspace.id]?.inbox ?? 0;
  return (
    <nav
      aria-label={`${workspace.name} sections`}
      className="flex flex-col gap-0.5"
    >
      {order.map((key) => {
        const s = TAB_SECTIONS[key];
        if (!s) return null;
        return (
          <NavLink
            key={key}
            href={base + s.path}
            exact={s.path === ""}
            icon={ICONS[key] ?? <DashboardIcon />}
            label={s.label}
            badge={key === "inbox" ? inbox : 0}
            onNavigate={onNavigate}
          >
            {s.label}
          </NavLink>
        );
      })}
    </nav>
  );
}
