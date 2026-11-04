import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getInbox, getWorkspace } from "@/data/queries";
import { LiveRefresh } from "@/shared/live-refresh";
import { InboxView } from "@/features/inbox/inbox-view";

export const metadata: Metadata = { title: "Inbox" };

export default async function InboxPage({
  params,
}: PageProps<"/w/[id]/inbox">) {
  const { id } = await params;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();
  const inbox = await getInbox(workspace.id);
  return (
    <>
      {/* New proposals and asks arrive while the page is open: a tick asks for
          the Inbox's count (one query in the core) and re-renders only when it
          moved. */}
      <LiveRefresh
        active
        everyMs={5000}
        stampUrl={`/api/w/${encodeURIComponent(workspace.id)}/inbox/stamp`}
        stamp={String(inbox.badge)}
      />
      <InboxView workspaceId={workspace.id} inbox={inbox} />
    </>
  );
}
