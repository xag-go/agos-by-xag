import { SettingsNav } from "@/features/workspaces/settings-nav";

export default async function WorkspaceSettingsLayout({
  params,
  children,
}: LayoutProps<"/w/[id]/settings">) {
  const { id } = await params;
  return (
    <div className="grid gap-6 md:grid-cols-[11rem_1fr]">
      <SettingsNav workspaceId={id} />
      <div className="flex min-w-0 flex-col gap-6">{children}</div>
    </div>
  );
}
