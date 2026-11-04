import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getTeam, getWorkHours, getWorkspace } from "@/data/queries";
import { WorkHoursSettings } from "@/features/workspaces/work-hours-settings";

export const metadata: Metadata = { title: "Work hours" };

/** The workspace's work hours (check-in / check-out per day) and who stays on today. */
export default async function WorkspaceWorkHoursPage({
  params,
}: PageProps<"/w/[id]/settings/work-hours">) {
  const { id } = await params;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();
  const [hours, team] = await Promise.all([
    getWorkHours(workspace.id),
    getTeam(workspace.id),
  ]);
  const titles: Record<string, string> = { "": team.cofounder.title };
  for (const m of team.members) if (m.name) titles[m.name] = m.title;
  return (
    <WorkHoursSettings
      workspaceId={workspace.id}
      hours={hours}
      titles={titles}
    />
  );
}
