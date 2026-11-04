import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  getChat,
  getChatAddresses,
  getConnectors,
  getChats,
  getModelCatalog,
  getWorkspace,
  getWorkspaceBots,
  parseId,
} from "@/data/queries";
import { ChatsView } from "@/features/chats/chats-view";

export const metadata: Metadata = { title: "Sessions" };

export default async function SessionsPage({
  params,
  searchParams,
}: PageProps<"/w/[id]/sessions">) {
  const { id } = await params;
  const { chat } = await searchParams;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();

  // Asked together; only the chat shown when none is asked (the newest) and its
  // addresses wait for what they depend on.
  const asked = parseId(typeof chat === "string" ? chat : undefined);
  const [chats, askedChat, catalog, connectors, connections] =
    await Promise.all([
      getChats(workspace.id),
      asked === null ? null : getChat(workspace.id, asked),
      getModelCatalog(),
      getConnectors(workspace.id),
      getWorkspaceBots(workspace.id),
    ]);
  const wanted = asked ?? chats[0]?.id ?? null;
  const current =
    asked !== null
      ? askedChat
      : wanted === null
        ? null
        : await getChat(workspace.id, wanted);

  return (
    <ChatsView
      workspaceId={workspace.id}
      chats={chats}
      current={current}
      asked={asked !== null && current !== null}
      catalog={catalog}
      agents={connectors
        .filter((c) => c.kind === "agent" && c.on)
        .map((c) => ({ name: c.name, title: c.title }))}
      addresses={
        current ? await getChatAddresses(workspace.id, current.id) : []
      }
      connections={connections}
    />
  );
}
