import { notFound } from "next/navigation";
import { getWorkspace } from "@/data/queries";
import { WorkspaceTitle } from "@/features/workspaces/workspace-title";

/** A workspace's pages: its menu is in the sidebar; here only the page's title. */
export default async function WorkspaceLayout({
  params,
  children,
}: LayoutProps<"/w/[id]">) {
  const { id } = await params;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();

  return (
    <div className="flex min-w-0 flex-col gap-6 has-[[data-fill]]:min-h-0 has-[[data-fill]]:flex-1">
      <WorkspaceTitle
        workspaceId={workspace.id}
        name={workspace.name}
        description={workspace.description}
      />
      {children}
    </div>
  );
}
