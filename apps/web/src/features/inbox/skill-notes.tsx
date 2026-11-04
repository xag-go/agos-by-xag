import Link from "next/link";

/** What AGOS's skill notes carry in their detail (Step 63, actions/skill_growth.py
 * `_close_batch` and actions/skill_requests.py `_end`). */
type ImprovedItem = {
  candidate: number;
  itemId: number;
  name: string;
  status: "promoted" | "discarded";
  from: number;
  to: number | null;
  why: string;
  note: string;
};
type Improved = { batch: string; items: ImprovedItem[] };
type Requested = {
  request: number;
  status: string;
  source: string;
  note: string;
};

function parsed<T>(detail: string): T | null {
  try {
    const found: unknown = JSON.parse(detail);
    return found && typeof found === "object" ? (found as T) : null;
  } catch {
    return null;
  }
}

/** The week's "Skills improved" note: each skill the review tested, what came of
 * it, and Skill Studio's Versions (diff and Restore) for the ones that changed. */
export function SkillsImprovedNote({
  workspaceId,
  detail,
}: {
  workspaceId: string;
  detail: string;
}) {
  const found = parsed<Improved>(detail);
  if (!found || !Array.isArray(found.items)) return null;
  const base = `/w/${encodeURIComponent(workspaceId)}/settings/capabilities/skills`;
  return (
    <ul className="mt-2 flex flex-col divide-y divide-line">
      {found.items.map((i) => (
        <li key={i.candidate} className="flex flex-col gap-0.5 py-2 first:pt-0">
          <p className="flex flex-wrap items-baseline gap-x-2 text-sm">
            <span className="font-medium">{i.name}</span>
            {i.status === "promoted" ? (
              <span className="text-xs text-success tabular-nums">
                v{i.from} → v{i.to ?? "?"}
              </span>
            ) : (
              <span className="text-xs text-ink-3">kept v{i.from}</span>
            )}
          </p>
          <p className="text-xs text-pretty text-ink-2">{i.why}</p>
          <p className="text-xs text-pretty text-ink-3">{i.note}</p>
          {i.status === "promoted" && (
            <Link
              href={`${base}/${String(i.itemId)}`}
              className="mt-0.5 self-start text-xs text-ink underline"
            >
              See the diff or restore v{i.from} in Skill Studio
            </Link>
          )}
        </li>
      ))}
    </ul>
  );
}

/** A find-skills request that ended (landed, failed, refused). */
export function SkillRequestNote({
  workspaceId,
  detail,
}: {
  workspaceId: string;
  detail: string;
}) {
  const found = parsed<Requested>(detail);
  if (!found) return null;
  return (
    <div className="mt-1 flex flex-col gap-1 text-sm text-ink-2">
      <p className="text-pretty">{found.note}</p>
      <p className="text-xs break-all text-ink-3">From {found.source}</p>
      <Link
        href={`/w/${encodeURIComponent(workspaceId)}/settings/skill-growth`}
        className="self-start text-xs text-ink underline"
      >
        All skill requests
      </Link>
    </div>
  );
}
