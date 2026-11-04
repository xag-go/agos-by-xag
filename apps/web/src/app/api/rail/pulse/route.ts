import { getBoardCounters, getWorkspaces } from "@/data/queries";
import type { RailPulse } from "@/features/shell/workspace-rail";
import { refuseUnlessOwner } from "@/server/access-guard";

/**
 * The workspace rail's dots: for every workspace, how many cards are being
 * worked on and how many wait for the owner (the same counters as its
 * dashboard; the core keeps them while Hermes's Kanban is unchanged). Polled
 * every few seconds by the rail. Same owner check as every action.
 */
export async function GET() {
  const refused = await refuseUnlessOwner();
  if (refused) return refused;
  const workspaces = await getWorkspaces();
  const pulse: RailPulse = {};
  await Promise.all(
    workspaces.map(async (w) => {
      try {
        const c = await getBoardCounters(w.id);
        pulse[w.id] = {
          working: c.working,
          waiting: c.waitingForYou,
          inbox: c.inbox,
        };
      } catch {
        // No Kanban, or Hermes didn't answer: no dot for this one.
      }
    }),
  );
  return Response.json(pulse, { headers: { "Cache-Control": "no-store" } });
}

export const dynamic = "force-dynamic";
