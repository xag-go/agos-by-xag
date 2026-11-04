import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  getAccountLimits,
  getActivity,
  getBoardCounters,
  getTeam,
  getUsagePrefs,
  getWorkspace,
  getWorkspaceOverview,
} from "@/data/queries";
import { Dashboard } from "@/features/dashboard/dashboard";

export const metadata: Metadata = { title: "Dashboard" };

export default async function DashboardPage({ params }: PageProps<"/w/[id]">) {
  const { id } = await params;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();

  // The overview is the slow read (Hermes's usage): not awaited here, its
  // cards stream in (Dashboard). The catch only keeps an early failure from
  // counting as unhandled before a card awaits it; the card still gets it.
  const overview = getWorkspaceOverview(workspace.id);
  void overview.catch(() => undefined);
  const [counters, limits, prefs, activity, team] = await Promise.all([
    getBoardCounters(workspace.id),
    getAccountLimits(),
    getUsagePrefs(),
    getActivity(workspace.id),
    getTeam(workspace.id),
  ]);

  return (
    <Dashboard
      workspace={workspace}
      counters={counters}
      limits={limits}
      warnAt={prefs.warnAt}
      activity={activity}
      overview={overview}
      team={team}
    />
  );
}
