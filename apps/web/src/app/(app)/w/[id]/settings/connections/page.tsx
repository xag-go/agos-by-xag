import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getMcpToken, getWorkspace } from "@/data/queries";
import { McpCard } from "@/features/connections/mcp-card";

export const metadata: Metadata = { title: "Connections" };

/** Settings → Connections: outside assistants over MCP. */
export default async function ConnectionsPage({
  params,
}: PageProps<"/w/[id]/settings/connections">) {
  const { id } = await params;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();
  const token = await getMcpToken(workspace.id);
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <McpCard workspaceId={workspace.id} name={workspace.name} token={token} />
    </div>
  );
}
