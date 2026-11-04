import type { Metadata } from "next";
import Link from "next/link";
import { getDefaultModel, getModelCatalog } from "@/data/queries";
import { firstChoice } from "@/features/models/first-choice";
import { ImportPanel } from "@/features/templates/import-panel";
import { TeamCatalog } from "@/features/templates/team-catalog";
import { NewWorkspaceForm } from "@/features/workspaces/new-workspace-form";
import { PageHeader } from "@/shared/ui/page-header";
import { Panel } from "@/shared/ui/panel";

export const metadata: Metadata = { title: "New workspace" };

export default async function NewWorkspacePage() {
  const [catalog, hermes] = await Promise.all([
    getModelCatalog(),
    getDefaultModel(),
  ]);
  // A new workspace starts on the model of the shared Hermes home (the one
  // General Settings writes). When that home has none (Hermes's own default
  // config leaves `model.default` empty), the form starts on the first model the
  // logged-in providers really offer: AGOS never picks a model of its own.
  const initial = hermes ?? firstChoice(catalog);

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        title="New workspace"
        description="One workspace per project. It gets its own folder, Kanban and chats, and can't see any other workspace."
      />
      {initial ? (
        <>
          <NewWorkspaceForm catalog={catalog} defaultModel={initial} />
          <Panel as="details" className="max-w-3xl p-5">
            <summary className="cursor-pointer font-display text-base font-semibold">
              Or start from a ready-made team
            </summary>
            <div className="mt-4">
              <TeamCatalog catalog={catalog} defaultModel={initial} />
            </div>
          </Panel>
          <Panel as="details" className="max-w-3xl p-5">
            <summary className="cursor-pointer font-display text-base font-semibold">
              Or import a workspace bundle
            </summary>
            <div className="mt-4">
              <ImportPanel
                workspaceId={null}
                catalog={catalog}
                defaultModel={initial}
              />
            </div>
          </Panel>
        </>
      ) : (
        <Panel as="p" className="max-w-2xl p-5 text-sm text-ink-2">
          No model to start on yet: connect a provider first in{" "}
          <Link href="/settings/models" className="underline">
            Settings → Models
          </Link>
          , then come back here.
        </Panel>
      )}
    </div>
  );
}
