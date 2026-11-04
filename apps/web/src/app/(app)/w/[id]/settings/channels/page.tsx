import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getTeamGroups, getWorkspace, getWorkspaceBots } from "@/data/queries";
import { HERMES_PLATFORMS } from "@/features/channels/hermes-platforms";
import { TeamGroup } from "@/features/channels/team-group";
import { WorkspaceBot } from "@/features/channels/workspace-bot";
import { PanelSection } from "@/shared/ui/panel";

export const metadata: Metadata = { title: "Channels" };

/** Where you can talk to this workspace besides the web app. */
export default async function WorkspaceChannelsPage({
  params,
  searchParams,
}: PageProps<"/w/[id]/settings/channels">) {
  const { id } = await params;
  const query = await searchParams;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();
  const [bots, groups] = await Promise.all([
    getWorkspaceBots(workspace.id),
    getTeamGroups(workspace.id),
  ]);
  return (
    <div className="flex max-w-3xl flex-col gap-8">
      <p className="text-sm text-ink-2">
        Talk to this workspace from other apps. You write, the Co-Founder
        answers, and Kanban notifications arrive there. Only your own account
        can write.
      </p>

      <Channel title="Telegram">
        <p className="text-sm text-ink-2">
          The workspace&apos;s own bot: its private chat with you is the
          Co-Founder chat.
        </p>
        <WorkspaceBot
          workspaceId={workspace.id}
          workspaceName={workspace.name}
          bots={bots}
          startWithQr={query.setup === "qr"}
        />
      </Channel>

      {bots.length > 0 && (
        <Channel title="Team group (Telegram topics)">
          <p className="text-sm text-ink-2">
            One Telegram group where each chat of this workspace gets its own
            topic: an agent, a session, a team chat. What is said in a topic is
            that chat, in AGOS too.
          </p>
          <TeamGroup workspaceId={workspace.id} groups={groups} />
        </Channel>
      )}

      <section className="flex flex-col gap-3">
        <div>
          <h2 className="font-display text-base font-semibold">
            More from Hermes
          </h2>
          <p className="mt-1 text-sm text-ink-2">
            Hermes can talk on these too. Each gets a Connect button here once
            AGOS supports it.
          </p>
        </div>
        <ul className="grid gap-2 sm:grid-cols-2">
          {HERMES_PLATFORMS.map((p) => (
            <li
              key={p.key}
              className="flex items-center justify-between gap-3 rounded-xl border border-line px-3 py-2.5"
            >
              <span className="flex min-w-0 flex-col">
                <span className="text-sm font-medium">{p.title}</span>
                <span className="truncate text-xs text-ink-3">{p.about}</span>
              </span>
              <span className="shrink-0 rounded-md bg-sunken px-1.5 py-0.5 text-xs text-ink-3">
                Coming
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function Channel({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <PanelSection className="flex flex-col gap-3 p-5">
      <h2 className="font-display text-base font-semibold">{title}</h2>
      {children}
    </PanelSection>
  );
}
