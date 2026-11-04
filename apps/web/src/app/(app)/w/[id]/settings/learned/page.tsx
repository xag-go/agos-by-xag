import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getLearned, getWorkspace, getWorkspaceBrain } from "@/data/queries";
import { BrainHere } from "@/features/proactive/brain-here";
import { LearnedList } from "@/features/proactive/proactive-settings";

export const metadata: Metadata = { title: "What I learned" };

export default async function Page({
  params,
}: PageProps<"/w/[id]/settings/learned">) {
  const { id } = await params;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();
  const [learned, methods] = await Promise.all([
    getLearned(workspace.id),
    getWorkspaceBrain(workspace.id),
  ]);
  return (
    <div className="flex flex-col gap-10">
      <LearnedList workspaceId={workspace.id} learned={learned} />
      <BrainHere workspaceId={workspace.id} methods={methods} />
    </div>
  );
}
