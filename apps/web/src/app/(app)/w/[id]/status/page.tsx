import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getStatusCards, getWorkspace } from "@/data/queries";
import { StatusView } from "@/features/status/status-view";

export const metadata: Metadata = { title: "Status" };

export default async function StatusPage({
  params,
}: PageProps<"/w/[id]/status">) {
  const { id } = await params;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();
  const page = await getStatusCards(workspace.id);
  return <StatusView workspaceId={workspace.id} page={page} />;
}
