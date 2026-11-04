import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getLabels, getWorkspace } from "@/data/queries";
import { LabelsSettings } from "@/features/workspaces/labels-settings";

export const metadata: Metadata = { title: "Labels" };

/** The workspace's card labels and their folders (label groups). */
export default async function WorkspaceLabelsPage({
  params,
}: PageProps<"/w/[id]/settings/labels">) {
  const { id } = await params;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();
  return (
    <LabelsSettings
      workspaceId={workspace.id}
      labels={await getLabels(workspace.id)}
    />
  );
}
