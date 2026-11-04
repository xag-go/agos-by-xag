import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getIdentity, getWorkspace } from "@/data/queries";
import { IdentitySettings } from "@/features/workspaces/identity-settings";

export const metadata: Metadata = { title: "Identity & memory" };

export default async function IdentityPage({
  params,
}: PageProps<"/w/[id]/settings/identity">) {
  const { id } = await params;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();
  return (
    <IdentitySettings
      workspaceId={workspace.id}
      identity={await getIdentity(workspace.id)}
    />
  );
}
