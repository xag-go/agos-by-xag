import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  getAccessLists,
  getAutonomy,
  getHermesSettings,
  getModelCatalog,
  getWorkspace,
  getWorkspaceFolders,
} from "@/data/queries";
import { WorkspaceSettings } from "@/features/workspaces/workspace-settings";

export const metadata: Metadata = { title: "Workspace settings" };

export default async function WorkspaceSettingsPage({
  params,
}: PageProps<"/w/[id]/settings">) {
  const { id } = await params;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();
  const [folders, catalog, hermes, autonomy, accessLists] = await Promise.all([
    getWorkspaceFolders(workspace.id),
    getModelCatalog(),
    getHermesSettings(workspace.id),
    getAutonomy(workspace.id),
    getAccessLists(workspace.id),
  ]);

  return (
    <WorkspaceSettings
      workspace={workspace}
      folders={folders}
      catalog={catalog}
      hermes={hermes}
      autonomy={autonomy}
      accessLists={accessLists}
    />
  );
}
