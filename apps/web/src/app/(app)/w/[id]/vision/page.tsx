import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getFolders, getVision, getWorkspace } from "@/data/queries";
import { VisionPage } from "@/features/vision/vision-view";

export const metadata: Metadata = { title: "Vision" };

export default async function VisionRoute({
  params,
}: PageProps<"/w/[id]/vision">) {
  const { id } = await params;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();
  // One read: the plan with its rollup from Hermes's Kanban, today, the rhythm
  // (and, next to it, the folders the owner groups the projects in).
  const [view, projectFolders] = await Promise.all([
    getVision(workspace.id),
    getFolders(workspace.id, "project").catch(() => []),
  ]);
  return (
    <VisionPage
      workspaceId={workspace.id}
      view={view}
      projectFolders={projectFolders}
    />
  );
}
