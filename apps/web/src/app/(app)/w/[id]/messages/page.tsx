import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  getChat,
  getChatAddresses,
  getModelCatalog,
  getTeam,
  getWorkspace,
  getWorkspaceBots,
  parseId,
} from "@/data/queries";
import { MessagesView } from "@/features/workers/messages-view";

export const metadata: Metadata = { title: "Team" };

export default async function MessagesPage({
  params,
  searchParams,
}: PageProps<"/w/[id]/messages">) {
  const { id } = await params;
  const { c } = await searchParams;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();
  const wanted = parseId(typeof c === "string" ? c : undefined);
  // Asked together; the chat asked for is read at once and shown only when it is
  // one of the team's (its addresses wait for it).
  const [team, opened, catalog, connections] = await Promise.all([
    getTeam(workspace.id),
    wanted === null ? null : getChat(workspace.id, wanted),
    getModelCatalog(),
    getWorkspaceBots(workspace.id),
  ]);
  // Only a DM or group of this workspace opens here (sessions stay in Sessions).
  const known = [...team.groups, ...team.dms].some((x) => x.id === wanted);
  const current = known ? opened : null;
  return (
    <MessagesView
      workspaceId={workspace.id}
      team={team}
      current={current}
      asked={current !== null}
      catalog={catalog}
      addresses={
        current ? await getChatAddresses(workspace.id, current.id) : []
      }
      connections={connections}
    />
  );
}
