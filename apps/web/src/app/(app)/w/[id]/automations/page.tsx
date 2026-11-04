import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  getAutomation,
  getAutomationEvents,
  getAutomationRevisions,
  getAutomationRunHistory,
  getAutomationRuns,
  getHooksAddress,
  getKanban,
  getPipelines,
  getAutomations,
  getFolders,
  getModelCatalog,
  getOngoing,
  getOwnerTimezone,
  getTicketPresets,
  getWorkspace,
  getWorkspaceAgents,
  getWorkHours,
  parseId,
} from "@/data/queries";
import { PipelinesSettings } from "@/features/pipelines/pipelines-settings";
import { AutomationHookDialog } from "@/features/setup/automation-hook";
import { AutomationModal } from "@/features/setup/automation-modal";
import { AutomationRuns } from "@/features/setup/automation-runs";
import { AutomationsList } from "@/features/setup/automations-list";
import { OngoingList } from "@/features/setup/ongoing-list";
import { RunHistory } from "@/features/setup/run-history";
import Link from "next/link";
import { ButtonLink } from "@/shared/ui/button";
import { PlusIcon } from "@/shared/ui/icons";

export const metadata: Metadata = { title: "Automations" };

export default async function AutomationsPage({
  params,
  searchParams,
}: PageProps<"/w/[id]/automations">) {
  const { id } = await params;
  const query = await searchParams;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();

  const baseHref = `/w/${workspace.id}/automations`;
  const editId = parseId(query.edit);
  const hookId = parseId(query.hook);
  const runsId = parseId(query.runs);
  // Asked together: clicking an automation (its form, webhook or runs) renders
  // the whole page again, so every read waits once, not one after the other.
  const modalOpen = query.new === "1" || editId !== null;
  const [
    catalog,
    editing,
    hookOf,
    runsOf,
    agents,
    automations,
    ongoing,
    { timezone },
    history,
    presets,
    rules,
    board,
    hours,
    folders,
  ] = await Promise.all([
    getModelCatalog(),
    editId === null ? null : getAutomation(workspace.id, editId),
    hookId === null ? null : getAutomation(workspace.id, hookId),
    runsId === null ? null : getAutomation(workspace.id, runsId),
    getWorkspaceAgents(workspace.id),
    getAutomations(workspace.id),
    getOngoing(workspace.id),
    getOwnerTimezone(),
    getAutomationRunHistory(workspace.id).catch(() => []),
    modalOpen ? getTicketPresets().catch(() => []) : [],
    getPipelines(workspace.id).catch(() => []),
    getKanban(workspace.id).catch(() => null),
    getWorkHours(workspace.id),
    getFolders(workspace.id, "automation").catch(() => []),
  ]);
  // The Rules form's pick lists (columns, members, goals, automations).
  const ruleLists = {
    columns: (board?.columns ?? [])
      .filter((c) => c.status !== "archived")
      .map((c) => ({ value: c.status, label: c.label })),
    members: (board?.members ?? []).map((m) => ({
      value: m.name,
      label: m.title || m.name,
    })),
    goals: (board?.goals ?? [])
      .filter((g) => g.level !== "vision")
      .map((g) => ({ value: String(g.id), label: g.title })),
    automations: automations.map((a) => ({
      value: String(a.id),
      label: a.name,
    })),
  };
  // What an open dialog shows of its automation (only once it exists).
  const [events, publicUrl, runs, revisions] = await Promise.all([
    hookOf ? getAutomationEvents(workspace.id, hookOf.id) : [],
    hookOf ? getHooksAddress() : "",
    runsOf ? getAutomationRuns(workspace.id, runsOf.id) : [],
    editing ? getAutomationRevisions(workspace.id, editing.id) : [],
  ]);

  return (
    <div className="flex flex-col gap-10">
      <nav aria-label="On this page" className="flex flex-wrap gap-2 text-sm">
        {(
          [
            ["#automations", "Automations"],
            ["#rules", "Rules"],
            ["#scheduled", "Scheduled by agents"],
            ...(ongoing.jobs.some((j) => j.system)
              ? ([["#system-rhythm", "System rhythm"]] as const)
              : []),
          ] as const
        ).map(([href, label]) => (
          <a
            key={href}
            href={href}
            className="rounded-full border border-line px-3 py-1 text-ink-2 hover:border-ink hover:text-ink"
          >
            {label}
          </a>
        ))}
      </nav>

      <section id="automations" className="flex scroll-mt-32 flex-col gap-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 className="font-display text-xl font-semibold">Automations</h2>
            <p className="mt-1 max-w-2xl text-sm text-ink-2">
              Work that starts by itself: on a schedule, or the moment something
              happens in another app (a webhook). Each automation says who does
              it: one member of the team, the Co-Founder, or the team together
              (steps on the Kanban, one agent after another). It runs by itself
              to the end and reports back here, unless you ask it to check with
              you first.
            </p>
          </div>
          <ButtonLink
            href={`${baseHref}?new=1`}
            scroll={false}
            variant="primary"
          >
            <PlusIcon />
            New automation
          </ButtonLink>
        </div>
        {hours?.on && (
          <p
            role="status"
            className="rounded-xl bg-sunken px-3.5 py-2 text-sm text-pretty text-ink-2 tabular-nums"
          >
            <span className="font-medium text-ink">
              {hours.checkOut
                ? `On the clock until ${hours.checkOutText}.`
                : `Off-hours until ${hours.nextCheckInText || "the next check-in"}.`}
            </span>{" "}
            Runs are paused off-hours: what falls due then runs at check-in (an
            agent you keep on today keeps its runs).{" "}
            <Link
              href={`/w/${workspace.id}/settings/work-hours`}
              className="underline underline-offset-2 hover:text-ink"
            >
              Work hours
            </Link>
          </p>
        )}
        <AutomationsList
          agents={agents}
          workspaceId={workspace.id}
          automations={automations}
          catalog={catalog}
          baseHref={baseHref}
          folders={folders}
        />
      </section>

      <section id="rules" className="scroll-mt-32">
        <PipelinesSettings
          workspaceId={workspace.id}
          rules={rules}
          lists={ruleLists}
        />
      </section>

      <RunHistory workspaceId={workspace.id} runs={history} />

      <OngoingList
        workspaceId={workspace.id}
        ongoing={ongoing}
        timezone={timezone}
      />

      {hookOf && (
        <AutomationHookDialog
          workspaceId={workspace.id}
          automation={hookOf}
          events={events}
          publicUrl={publicUrl}
          closeHref={baseHref}
        />
      )}

      {runsOf && (
        <AutomationRuns
          workspaceId={workspace.id}
          automation={runsOf}
          runs={runs}
          closeHref={baseHref}
        />
      )}

      {(query.new === "1" || editing) && (
        <AutomationModal
          workspaceId={workspace.id}
          key={editing?.id ?? "new"}
          automation={editing}
          catalog={catalog}
          defaultModel={workspace.defaultModel}
          closeHref={baseHref}
          agents={agents}
          revisions={revisions}
          presets={presets}
        />
      )}
    </div>
  );
}
