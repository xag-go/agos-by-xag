import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getWorkspace, getWorkspaceLog } from "@/data/queries";
import { LiveRefresh } from "@/shared/live-refresh";
import { logFilters } from "@/features/log/log-filters";
import { WorkspaceLog } from "@/features/log/workspace-log";
import { stampOf } from "@/server/stamp";

export const metadata: Metadata = { title: "Log" };

export default async function LogPage({
  params,
  searchParams,
}: PageProps<"/w/[id]/log">) {
  const { id } = await params;
  const query = await searchParams;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();
  const filters = logFilters((name) => query[name]);
  const { level, area, q, actor, since, until } = filters;
  const before = typeof query.before === "string" ? query.before : undefined;
  const page = await getWorkspaceLog(workspace.id, { ...filters, before });
  return (
    <>
      {/* The newest entries keep coming in while the page is open. A tick asks
          for the first page's fingerprint and re-renders only when it moved. */}
      <LiveRefresh
        active={!before}
        everyMs={10000}
        stampUrl={`/api/w/${encodeURIComponent(workspace.id)}/log/stamp?${new URLSearchParams(
          {
            level,
            ...(area ? { area } : {}),
            ...(q ? { q } : {}),
            ...(actor ? { actor } : {}),
            ...(since ? { since } : {}),
            ...(until ? { until } : {}),
          },
        ).toString()}`}
        stamp={stampOf(page)}
      />
      <WorkspaceLog
        baseHref={`/w/${workspace.id}/log`}
        page={page}
        level={level}
        area={area}
        q={q}
        actor={actor}
        since={since}
        until={until}
        before={before}
      />
    </>
  );
}
