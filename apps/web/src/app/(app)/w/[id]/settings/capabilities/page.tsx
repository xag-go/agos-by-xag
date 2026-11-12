import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  getConnectors,
  getFolders,
  getSkillUpdates,
  getWorkspace,
  getWorkspaceApps,
  getWorkspaceMcp,
  getWorkspaceSkills,
} from "@/data/queries";
import { ConnectorsList } from "@/features/setup/connectors-list";

export const metadata: Metadata = { title: "Capabilities" };

export default async function CapabilitiesPage({
  params,
}: PageProps<"/w/[id]/settings/capabilities">) {
  const { id } = await params;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();
  const [connectors, apps, mcp, skills, skillUpdates, skillFolders] =
    await Promise.all([
      getConnectors(workspace.id),
      getWorkspaceApps(workspace.id),
      getWorkspaceMcp(workspace.id),
      getWorkspaceSkills(workspace.id),
      getSkillUpdates(workspace.id),
      getFolders(workspace.id, "skill").catch(() => []),
    ]);

  return (
    <>
      <p className="max-w-2xl text-sm text-ink-2">
        What this workspace may use. Every built-in tool is on from the start;
        turn off what you don&apos;t want. Skills, agents, apps and MCP servers
        are this workspace&apos;s own, with its own accounts and keys; its
        Co-Founder and agents share its skills.
      </p>
      <ConnectorsList
        workspaceId={workspace.id}
        connectors={connectors}
        apps={apps}
        mcp={mcp}
        skills={skills}
        skillUpdates={skillUpdates}
        skillFolders={skillFolders}
      />
    </>
  );
}
