import type { Metadata } from "next";
import { notFound } from "next/navigation";
import type { KanbanCard } from "@/data/types";
import { getOfficeView, getWorkspace } from "@/data/queries";
import { openStatuses } from "@/features/office/model";
import { Office3D as Office } from "@/features/office3d/office3d";

export const metadata: Metadata = { title: "Office" };

/** The Office never shows a card's text, so it isn't sent to the browser (on a
 * big Kanban that text is most of the page's data, sent again on every refresh). */
function withoutText(cards: KanbanCard[]): KanbanCard[] {
  return cards.map((c) => ({ ...c, body: "" }));
}

export default async function OfficePage({
  params,
}: PageProps<"/w/[id]/office">) {
  const { id } = await params;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();
  // One read: the team, Hermes's Kanban and the looks, with the fingerprint of
  // exactly that data (what the live refresh compares).
  const { team, board, looks, stamp } = await getOfficeView(workspace.id);
  return (
    <Office
      workspaceId={workspace.id}
      workspaceName={workspace.name}
      team={team}
      cards={withoutText(board?.cards ?? [])}
      open={openStatuses(board?.columns ?? [])}
      looks={looks}
      connected={board !== null}
      stamp={stamp}
    />
  );
}
