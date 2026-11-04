import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getSkillGrowth, getWorkspace } from "@/data/queries";
import { SkillGrowthSettings } from "@/features/workspaces/skill-growth-settings";

export const metadata: Metadata = { title: "Skills that grow" };

/** Find-skills requests and the weekly skill review (Step 63). */
export default async function WorkspaceSkillGrowthPage({
  params,
}: PageProps<"/w/[id]/settings/skill-growth">) {
  const { id } = await params;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();
  return (
    <SkillGrowthSettings
      workspaceId={workspace.id}
      growth={await getSkillGrowth(workspace.id).catch(() => null)}
    />
  );
}
