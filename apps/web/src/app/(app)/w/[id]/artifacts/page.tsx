import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getArtifacts, getWorkspace } from "@/data/queries";
import { ArtifactsView } from "@/features/artifacts/artifacts-view";

export const metadata: Metadata = { title: "Artifacts" };

export default async function ArtifactsPage({
  params,
}: PageProps<"/w/[id]/artifacts">) {
  const { id } = await params;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();
  // One read: every card's files (Hermes's attachments) and documents, with reviews.
  const page = await getArtifacts(workspace.id);
  return <ArtifactsView workspaceId={workspace.id} page={page} />;
}
