import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getWorkspace } from "@/data/queries";
import { ImportPanel } from "@/features/templates/import-panel";
import { buttonClass } from "@/shared/ui/button";
import { PanelSection } from "@/shared/ui/panel";

export const metadata: Metadata = { title: "Export / Import" };

/** Settings → Export / Import: this workspace as a readable bundle (download),
 * and a bundle into it (preview, collisions, keys, fidelity report). */
export default async function ExportImportPage({
  params,
}: PageProps<"/w/[id]/settings/export">) {
  const { id } = await params;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <PanelSection className="flex flex-col gap-3 p-5">
        <h2 className="font-display text-base font-semibold">Export</h2>
        <p className="text-sm text-ink-2">
          The team (TEAM.md), each member&apos;s role
          (agents/&lt;name&gt;/SOUL.md and agent.yaml), the skills, the
          automations, the Vision and the settings, as markdown and YAML you can
          read. No key, token or login is in it: each key the team uses is
          listed by name, and asked for when the bundle is imported. Chats,
          memory, cards and Telegram stay here.
        </p>
        <div>
          <a
            href={`/api/w/${workspace.id}/export`}
            download
            className={buttonClass("primary")}
          >
            Download the bundle
          </a>
        </div>
      </PanelSection>
      <PanelSection className="flex flex-col gap-3 p-5">
        <h2 className="font-display text-base font-semibold">
          Import into this workspace
        </h2>
        <p className="text-sm text-ink-2">
          Members, skills and automations are added the normal way. When this
          workspace already has one with the same name, you choose: keep yours,
          add a copy, or replace yours.
        </p>
        <ImportPanel workspaceId={workspace.id} />
      </PanelSection>
    </div>
  );
}
