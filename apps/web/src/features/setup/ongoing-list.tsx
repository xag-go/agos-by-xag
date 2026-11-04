import type { Ongoing } from "@/data/queries";
import { ButtonLink } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { OngoingStop } from "./ongoing-stop";
import { PanelSection } from "@/shared/ui/panel";

/** Dates in the owner's own timezone (Settings → General), the same on every
 * device; the server's clock is not his. */
function when(iso: string | null | undefined, zone: string): string {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat("en-GB", {
      weekday: "short",
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      ...(zone ? { timeZone: zone } : {}),
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

/** Hermes's job states (cron/jobs.py) in the owner's words. */
const JOB_STATE: Record<string, string> = {
  scheduled: "On",
  paused: "Paused",
  completed: "Done",
  error: "Error",
};

/** AGOS's own rhythm jobs in the owner's words, and where he changes each. */
const SYSTEM: Record<
  string,
  {
    label: string;
    about: string;
    where: "vision" | "hierarchy" | "settings/skill-growth";
  }
> = {
  daily: {
    label: "Daily plan",
    about: "The Co-Founder proposes today's plan: what you and each member do.",
    where: "vision",
  },
  recap: {
    label: "Evening recap",
    about:
      "The Co-Founder tells you how today went: done, left, moves to tomorrow.",
    where: "vision",
  },
  weekly: {
    label: "Weekly review",
    about:
      "The Co-Founder reviews the goals' key results and proposes changes.",
    where: "vision",
  },
  heartbeat: {
    label: "Co-Founder heartbeat",
    about:
      "The Co-Founder wakes up and checks its cards, questions and the team's blocked work.",
    where: "hierarchy",
  },
  skills: {
    label: "Weekly skill review",
    about:
      "The Co-Founder reads the week's corrections and errors and tests better versions of the skills involved.",
    where: "settings/skill-growth",
  },
};

type Job = Ongoing["jobs"][number];

function State({ job }: { job: Job }) {
  return (
    <span
      className={cn(
        "rounded-full px-2 py-0.5 text-xs",
        job.state === "scheduled"
          ? "bg-accent-soft"
          : job.state === "error"
            ? "bg-danger-soft text-danger"
            : "bg-sunken text-ink-3",
      )}
      title={job.pausedReason ?? undefined}
    >
      {JOB_STATE[job.state] ?? job.state}
    </span>
  );
}

function Times({ job, timezone }: { job: Job; timezone: string }) {
  return (
    <p className="mt-1 text-xs text-ink-2">
      {job.schedule} · next {when(job.nextRunAt, timezone)}
      {job.lastRunAt ? ` · last ${when(job.lastRunAt, timezone)}` : ""}
    </p>
  );
}

/** The jobs the agents scheduled in the workspace's Hermes (a reminder to come
 * back to him, an eye kept on something; Stop removes one), and AGOS's own rhythm
 * jobs apart (changed on the Vision page / the agent card, not stopped here). */
export function OngoingList({
  workspaceId,
  ongoing,
  timezone,
}: {
  workspaceId: string;
  ongoing: Ongoing;
  timezone: string;
}) {
  const system = ongoing.jobs.filter((j) => j.system);
  const agents = ongoing.jobs.filter((j) => !j.system);
  return (
    <>
      <PanelSection id="scheduled" className="scroll-mt-32">
        <h3 className="border-b border-line px-5 py-3 text-sm font-medium">
          Scheduled by the agents
        </h3>
        {agents.length === 0 ? (
          <p className="px-5 py-6 text-sm text-ink-3">
            None yet. Tell an agent “remind me at 6…” or “check this page every
            hour” and it schedules it here.
          </p>
        ) : (
          <ul className="divide-y divide-line">
            {agents.map((j) => (
              <li
                key={j.id}
                className="flex flex-wrap items-start gap-x-6 gap-y-2 px-5 py-4"
              >
                <div className="min-w-64 flex-1">
                  <p className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{j.name || j.prompt}</span>
                    <State job={j} />
                  </p>
                  {j.name && j.prompt ? (
                    <p className="mt-1 line-clamp-2 text-xs text-ink-2">
                      {j.prompt}
                    </p>
                  ) : null}
                  <Times job={j} timezone={timezone} />
                </div>
                <OngoingStop
                  workspaceId={workspaceId}
                  id={j.id}
                  label={j.name || j.prompt}
                />
              </li>
            ))}
          </ul>
        )}
      </PanelSection>

      {system.length > 0 && (
        <PanelSection id="system-rhythm" className="scroll-mt-32">
          <div className="border-b border-line px-5 py-3">
            <h3 className="text-sm font-medium">System rhythm</h3>
            <p className="mt-0.5 text-xs text-ink-3">
              AGOS runs these for the Co-Founder. Change their time or turn them
              off where each one lives.
            </p>
          </div>
          <ul className="divide-y divide-line">
            {system.map((j) => {
              const s = SYSTEM[j.system ?? ""];
              return (
                <li
                  key={j.id}
                  className="flex flex-wrap items-start gap-x-6 gap-y-2 px-5 py-4"
                >
                  <div className="min-w-64 flex-1">
                    <p className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{s?.label ?? j.name}</span>
                      <State job={j} />
                    </p>
                    {s && <p className="mt-1 text-xs text-ink-2">{s.about}</p>}
                    <Times job={j} timezone={timezone} />
                  </div>
                  <ButtonLink
                    href={`/w/${encodeURIComponent(workspaceId)}/${s?.where ?? "vision"}`}
                  >
                    {s?.where === "hierarchy"
                      ? "Agent card"
                      : s?.where === "settings/skill-growth"
                        ? "Skill settings"
                        : "Vision page"}
                  </ButtonLink>
                </li>
              );
            })}
          </ul>
        </PanelSection>
      )}
    </>
  );
}
