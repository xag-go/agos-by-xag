import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getToolKeys, getWorkspace } from "@/data/queries";
import { ToolKeysCard } from "@/features/workspaces/tool-keys";

export const metadata: Metadata = { title: "Keys" };

/** Keys for this workspace's own tools and scripts (Hermes keeps them). */
export default async function WorkspaceKeysPage({
  params,
}: PageProps<"/w/[id]/settings/keys">) {
  const { id } = await params;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();
  return (
    <ToolKeysCard
      workspaceId={workspace.id}
      data={await getToolKeys(workspace.id)}
    />
  );
}
