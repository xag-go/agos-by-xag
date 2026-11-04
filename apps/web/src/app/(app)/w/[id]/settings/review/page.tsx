import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getReviewSettings, getWorkspace } from "@/data/queries";
import { ReviewSettingsCard } from "@/features/workspaces/review-settings";

export const metadata: Metadata = { title: "Review" };

/** The workspace's review defaults: stages, round cap, plan first. */
export default async function WorkspaceReviewPage({
  params,
}: PageProps<"/w/[id]/settings/review">) {
  const { id } = await params;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();
  return (
    <ReviewSettingsCard
      workspaceId={workspace.id}
      settings={await getReviewSettings(workspace.id)}
    />
  );
}
