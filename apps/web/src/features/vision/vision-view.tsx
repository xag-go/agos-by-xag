"use client";

import { useState } from "react";
import type { ListFolder, VisionView } from "@/data/types";
import { Input, Select } from "@/shared/ui/field";
import { PageActions } from "@/features/workspaces/page-actions";
import { Button } from "@/shared/ui/button";
import { FormStatus } from "@/shared/ui/form-status";
import { Switch } from "@/shared/ui/switch";
import { setRhythm } from "./actions";
import { planIndex } from "./format";
import { GoalList } from "./goals";
import { NotesBox, type VisionPreview } from "./notes-box";
import { TodaySection } from "./today";
import { useRun } from "./use-run";
import { VisionForm, VisionHero } from "./vision-form";

type RhythmJob = NonNullable<VisionView["rhythm"]>[number];

const DAYS = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
];
const JOB_WORDS: Record<RhythmJob["which"], string> = {
  daily:
    "Daily plan: what you and each member do today (Accept / Change / Skip)",
  recap: "Evening recap: done, left, what moves to tomorrow",
  weekly: "Weekly review: key results' numbers and changes to the plan",
};
const JOB_SHORT: Record<RhythmJob["which"], string> = {
  daily: "Plan",
  recap: "Recap",
  weekly: "Weekly",
};

/**
 * The workspace's plan (owner's pick V3, Today on the right): the Vision hero
 * on top (its why and strategy behind a toggle), the notes and the
 * Co-Founder's rhythm folded side by side under it, then two columns: the
 * goals with their key results (projects folded) and Today's one card (the
 * owner's part over the team's cards), sticky on wide screens. Below ~1100px
 * Today comes first. Each part opens its form only on Edit or +; the
 * Co-Founder proposes goals, numbers, projects and each day's plan in the
 * Inbox.
 */
export function VisionPage({
  workspaceId,
  view,
  projectFolders = [],
}: {
  workspaceId: string;
  view: VisionView;
  /** The owner's folders of the projects (AGOS's own grouping). */
  projectFolders?: ListFolder[];
}) {
  const vision = view.vision ?? null;
  const members = view.members ?? [];
  const rhythm = view.rhythm ?? [];
  const goals = (vision?.children ?? []).filter((g) => g.level === "goal");
  const index = planIndex(goals);
  // One goal's edit form at a time (its Edit, or a key result chip).
  const [editing, setEditing] = useState<number | null>(null);
  // The Vision's own form (the hero's Edit, or the page's "Edit vision").
  const [visionEditing, setVisionEditing] = useState(false);
  // Organize's last answer (with a stamp: each one opens the form afresh).
  const [preview, setPreview] = useState<{
    at: number;
    shown: VisionPreview;
  } | null>(null);
  const notes = (
    <NotesBox
      workspaceId={workspaceId}
      notes={view.notes ?? null}
      folded={vision !== null}
      onOrganized={(shown) => {
        setPreview({ at: Date.now(), shown });
      }}
    />
  );
  if (!vision)
    return (
      <div className="flex flex-col gap-6">
        {notes}
        <VisionForm
          key={preview?.at ?? "new"}
          workspaceId={workspaceId}
          vision={null}
          preview={preview?.shown ?? null}
          onSaved={() => {
            setPreview(null);
          }}
        />
      </div>
    );
  return (
    <div className="flex flex-col gap-3.5 pb-6">
      <PageActions>
        <Button
          className="!h-9 !rounded-10 !border-0 !px-3.5 font-semibold text-ink-2 !shadow-vision-card transition-[scale] active:scale-[0.96]"
          aria-label="Edit the Vision, why and strategy"
          onClick={() => {
            setVisionEditing(true);
          }}
        >
          Edit vision
        </Button>
      </PageActions>
      <VisionHero
        key={preview?.at ?? "saved"}
        workspaceId={workspaceId}
        vision={vision}
        today={view.today.date}
        goals={goals}
        editing={visionEditing || preview !== null}
        onEditing={(on) => {
          setVisionEditing(on);
          if (!on) setPreview(null);
        }}
        preview={preview?.shown ?? null}
        onSaved={() => {
          setPreview(null);
        }}
      />
      <div className="flex flex-wrap gap-3.5">
        {notes}
        <RhythmSettings workspaceId={workspaceId} jobs={rhythm} />
      </div>
      <div className="vision-cols mt-5">
        <div className="vision-today min-w-0">
          <TodaySection
            workspaceId={workspaceId}
            today={view.today}
            rhythm={rhythm}
            index={index}
            goals={goals}
          />
        </div>
        <div className="vision-goals min-w-0">
          <GoalList
            workspaceId={workspaceId}
            goals={goals}
            members={members}
            editing={editing}
            onEdit={setEditing}
            folders={projectFolders}
          />
        </div>
      </div>
    </div>
  );
}

function RhythmRow({
  workspaceId,
  job,
}: {
  workspaceId: string;
  job: RhythmJob;
}) {
  const [busy, error, run] = useRun();
  const [time, setTime] = useState(job.time);
  const [day, setDay] = useState<number | null>(job.day ?? null);
  const save = (on: boolean, nextTime = time, nextDay = day) => {
    run(() =>
      setRhythm(workspaceId, job.which, { on, time: nextTime, day: nextDay }),
    );
  };
  return (
    <li className="flex flex-col gap-1 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <Switch
          label={job.name}
          defaultOn={job.on}
          disabled={busy}
          onChange={(on) => {
            save(on);
          }}
        />
        <span className="min-w-48 flex-1 text-sm">{JOB_WORDS[job.which]}</span>
        {job.which === "weekly" && (
          <Select
            aria-label="Day"
            className="h-8 !w-auto text-xs"
            value={String(day ?? 5)}
            disabled={busy}
            onChange={(e) => {
              const next = Number(e.target.value);
              setDay(next);
              save(job.on, time, next);
            }}
          >
            {DAYS.map((d, i) => (
              <option key={d} value={String(i)}>
                {d}
              </option>
            ))}
          </Select>
        )}
        <Input
          type="time"
          aria-label={`${job.name} time`}
          className="h-8 !w-auto text-xs"
          value={time}
          disabled={busy}
          onChange={(e) => {
            setTime(e.target.value);
          }}
          onBlur={() => {
            if (time !== job.time) save(job.on);
          }}
        />
        <span className="text-xs text-ink-3">your time</span>
      </div>
      <p className="text-11 text-ink-3">
        {job.lastAt ? `Last run ${job.lastAt}` : "Not run yet"}
        {job.on && job.nextAt ? ` · next ${job.nextAt}` : ""}
        {job.problem ? ` · ${job.problem}` : ""}
      </p>
      <FormStatus error={error} />
    </li>
  );
}

function RhythmSettings({
  workspaceId,
  jobs,
}: {
  workspaceId: string;
  jobs: RhythmJob[];
}) {
  const times = jobs
    .filter((j) => j.on)
    .map(
      (j) =>
        `${JOB_SHORT[j.which]} ${j.which === "weekly" && j.day !== null && j.day !== undefined ? `${(DAYS[j.day] ?? "").slice(0, 3)} ` : ""}${j.time}`,
    );
  return (
    <details className="group min-w-0 flex-1 basis-[20rem] rounded-14 bg-panel/75 shadow-vision-card open:basis-full open:bg-panel">
      <summary className="flex min-h-12 cursor-pointer list-none items-center gap-2.5 px-5 py-3 text-13.5 font-semibold text-ink-2 [&::-webkit-details-marker]:hidden">
        <span
          aria-hidden
          className="text-xs text-ink-3 transition-transform duration-150 group-open:rotate-90"
        >
          ▸
        </span>
        <span className="shrink-0 whitespace-nowrap">
          Co-Founder&apos;s rhythm
        </span>
        <span className="ml-auto min-w-0 truncate text-12.5 font-normal text-ink-3 tabular-nums">
          {times.length > 0 ? times.join(" · ") : "All off"}
        </span>
      </summary>
      <div className="px-[18px] pb-4">
        <p className="text-xs text-ink-3">
          Hermes runs these in the Co-Founder&apos;s own schedule (times in your
          timezone from Settings → General, else this server&apos;s). Each posts
          to your Inbox and its Telegram chat; turn any of them off here.
        </p>
        <ul className="mt-2 divide-y divide-line">
          {jobs.map((j) => (
            <RhythmRow key={j.which} workspaceId={workspaceId} job={j} />
          ))}
        </ul>
      </div>
    </details>
  );
}
