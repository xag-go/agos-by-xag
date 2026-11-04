import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  getCopyableAgents,
  getDocs,
  getFounder,
  getHeartbeats,
  getHiresAsked,
  getModelCatalog,
  getProposals,
  getScorecards,
  getTeam,
  getWorkspace,
  getWorkspaceAgents,
} from "@/data/queries";
import { Hierarchy } from "@/features/workers/hierarchy";

export const metadata: Metadata = { title: "Hierarchy" };

export default async function HierarchyPage({
  params,
}: PageProps<"/w/[id]/hierarchy">) {
  const { id } = await params;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();
  const [
    team,
    agents,
    copyable,
    catalog,
    docs,
    proposals,
    heartbeats,
    asked,
    scorecards,
    founder,
  ] = await Promise.all([
    getTeam(workspace.id),
    getWorkspaceAgents(workspace.id),
    getCopyableAgents(workspace.id),
    getModelCatalog(),
    getDocs(workspace.id),
    getProposals(workspace.id).catch(() => []),
    getHeartbeats(workspace.id).catch(() => []),
    getHiresAsked(workspace.id).catch(() => ({ card: null })),
    getScorecards(workspace.id).catch(() => null),
    getFounder(workspace.id).catch(() => null),
  ]);
  return (
    <Hierarchy
      workspaceId={workspace.id}
      workspaceName={workspace.name}
      team={team}
      cofounderModel={workspace.defaultModel}
      agents={agents}
      pending={proposals.filter((p) => p.kind === "hire")}
      copyable={copyable}
      catalog={catalog}
      heartbeats={heartbeats}
      hiresCard={asked.card ?? null}
      scorecards={scorecards}
      founder={founder}
      docFiles={docs.files
        .filter((f) => f.rule)
        .map((f) => ({ path: f.path, sections: f.sections }))}
    />
  );
}
