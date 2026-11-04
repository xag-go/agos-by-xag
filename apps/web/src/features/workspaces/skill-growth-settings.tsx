"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import type { SkillCandidate, SkillGrowth, SkillRequest } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { Field, Input, Select } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { Switch } from "@/shared/ui/switch";
import { saveSkillRequestLimit, saveSkillReview } from "./skill-growth-actions";
import { PanelSection } from "@/shared/ui/panel";

const DAYS = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
];

const REQUEST_WORDS: Record<string, string> = {
  installing: "Installing",
  testing: "Testing",
  approval: "Waiting for you",
  landed: "Added",
  failed: "Failed its tests",
  refused: "Refused",
  rejected: "You said no",
};

const CANDIDATE_WORDS: Record<string, string> = {
  testing: "Testing",
  promoted: "New version",
  discarded: "Kept the old one",
};

/**
 * Workspace settings → Skills that grow: how many hub skills the agents may ask
 * for per day, the Co-Founder's weekly skill review (Hermes's cron job), and the
 * log of both. Every install and every new version goes through Hermes; this is
 * only where the owner sees and steers it.
 */
export function SkillGrowthSettings({
  workspaceId,
  growth,
}: {
  workspaceId: string;
  growth: SkillGrowth | null;
}) {
  if (growth === null)
    return (
      <p className="text-sm text-ink-2">
        The skill settings can&apos;t be read right now.
      </p>
    );
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <p className="text-sm text-pretty text-ink-2">
        When an agent lacks a skill, it searches this workspace, then
        Hermes&apos;s skills hub, and asks for one. Hermes installs it with its
        security scan, switched off; the agent&apos;s own tests run in Skill
        Studio; a skill with scripts or a scan warning waits for you in the
        Inbox. Once a week the Co-Founder reads what went wrong and tests better
        versions of the skills involved; only a version that passes every test
        and scores at least as well replaces the current one.
      </p>
      <LimitSection workspaceId={workspaceId} growth={growth} />
      <ReviewSection workspaceId={workspaceId} growth={growth} />
      <RequestsSection workspaceId={workspaceId} requests={growth.requests} />
      <CandidatesSection
        workspaceId={workspaceId}
        candidates={growth.candidates}
      />
    </div>
  );
}

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <PanelSection aria-labelledby={id} className="flex flex-col gap-4 p-5">
      <h2 id={id} className="font-display text-base font-semibold">
        {title}
      </h2>
      {children}
    </PanelSection>
  );
}

function LimitSection({
  workspaceId,
  growth,
}: {
  workspaceId: string;
  growth: SkillGrowth;
}) {
  const [limit, setLimit] = useState(String(growth.limit));
  const [busy, start] = useTransition();
  const [status, setStatus] = useState<{
    error: string | null;
    saved?: boolean;
  }>({ error: null });
  return (
    <Section id="skill-requests-title" title="Skill requests">
      <Field
        label="Requests per day"
        hint={`For the whole team, counted per UTC day; 0 stops them. Used today: ${String(growth.usedToday)}.`}
      >
        <div className="flex items-center gap-3">
          <Input
            type="number"
            min={0}
            max={20}
            value={limit}
            disabled={busy}
            className="w-24 tabular-nums"
            onChange={(e) => {
              setLimit(e.currentTarget.value);
            }}
          />
          <Button
            disabled={busy}
            onClick={() => {
              start(async () => {
                setStatus(
                  await saveSkillRequestLimit(workspaceId, Number(limit) || 0),
                );
              });
            }}
          >
            Save
          </Button>
          <FormStatus error={status.error} saved={status.saved} />
        </div>
      </Field>
    </Section>
  );
}

function ReviewSection({
  workspaceId,
  growth,
}: {
  workspaceId: string;
  growth: SkillGrowth;
}) {
  const { job } = growth;
  const [on, setOn] = useState(job.on);
  const [day, setDay] = useState(String(job.day));
  const [time, setTime] = useState(job.time);
  const [busy, start] = useTransition();
  const [status, setStatus] = useState<{
    error: string | null;
    saved?: boolean;
  }>({ error: null });
  return (
    <Section id="skill-review-title" title="Weekly skill review">
      <Switch
        defaultOn={on}
        disabled={busy}
        label="The Co-Founder reviews the week's skill evidence"
        onChange={setOn}
      />
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Day">
          <Select
            value={day}
            disabled={busy}
            onChange={(e) => {
              setDay(e.currentTarget.value);
            }}
          >
            {DAYS.map((d, i) => (
              <option key={d} value={String(i)}>
                {d}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Time (your timezone)">
          <Input
            type="time"
            value={time}
            disabled={busy}
            className="w-32 tabular-nums"
            onChange={(e) => {
              setTime(e.currentTarget.value);
            }}
          />
        </Field>
        <Button
          disabled={busy}
          onClick={() => {
            start(async () => {
              setStatus(
                await saveSkillReview(workspaceId, {
                  on,
                  time,
                  day: Number(day),
                }),
              );
            });
          }}
        >
          Save
        </Button>
        <FormStatus error={status.error} saved={status.saved} />
      </div>
      <p className="text-xs text-ink-3">
        A Hermes cron job on the Co-Founder, after the weekly review. With no
        evidence it stops before any model runs.
        {job.lastAt && ` Last run ${job.lastAt.slice(0, 16).replace("T", " ")}`}
        {job.lastStatus && ` (${job.lastStatus})`}
        {job.lastAt && "."}
        {job.problem && ` ${job.problem}`}
      </p>
    </Section>
  );
}

function StatusChip({
  words,
  tone,
}: {
  words: string;
  tone: "ok" | "wait" | "off" | "busy";
}) {
  return (
    <span
      className={cn(
        "shrink-0 rounded px-1.5 py-px text-11 font-medium",
        tone === "ok" && "bg-success/15 text-success",
        tone === "wait" && "bg-attention text-attention-ink",
        tone === "off" && "bg-sunken text-ink-3",
        tone === "busy" && "bg-live/15 text-live",
      )}
    >
      {words}
    </span>
  );
}

function requestTone(r: SkillRequest): "ok" | "wait" | "off" | "busy" {
  if (r.status === "landed") return "ok";
  if (r.status === "approval") return "wait";
  if (r.status === "installing" || r.status === "testing") return "busy";
  return "off";
}

function RequestsSection({
  workspaceId,
  requests,
}: {
  workspaceId: string;
  requests: SkillRequest[];
}) {
  return (
    <Section id="skill-request-log-title" title="Requests">
      {requests.length === 0 ? (
        <p className="text-sm text-ink-3">
          No agent has asked for a skill yet.
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-line">
          {requests.map((r) => (
            <li key={r.id} className="flex flex-col gap-0.5 py-2.5 first:pt-0">
              <div className="flex items-baseline gap-2">
                <span className="truncate text-sm font-medium">{r.name}</span>
                <StatusChip
                  words={REQUEST_WORDS[r.status] ?? r.status}
                  tone={requestTone(r)}
                />
                <span className="ml-auto shrink-0 text-xs text-ink-3 tabular-nums">
                  @{r.member || "cofounder"} · {r.createdAt.slice(0, 10)}
                </span>
              </div>
              <p className="text-xs break-all text-ink-3">
                {r.source}
                {r.verdict && ` · scan ${r.verdict}`}
                {r.scripts && " · has scripts"}
                {r.forced && " · installed with your yes"}
              </p>
              <p className="text-xs text-pretty text-ink-2">{r.reason}</p>
              {r.note && (
                <p className="text-xs text-pretty text-ink-3">{r.note}</p>
              )}
              {r.itemId !== null && r.status !== "rejected" && (
                <Link
                  href={`/w/${encodeURIComponent(workspaceId)}/settings/capabilities/skills/${String(r.itemId)}`}
                  className="self-start text-xs text-ink underline"
                >
                  Skill Studio
                </Link>
              )}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function CandidatesSection({
  workspaceId,
  candidates,
}: {
  workspaceId: string;
  candidates: SkillCandidate[];
}) {
  return (
    <Section id="skill-candidates-title" title="Versions the review tried">
      {candidates.length === 0 ? (
        <p className="text-sm text-ink-3">
          Nothing yet. The review only writes when the week shows a skill went
          wrong.
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-line">
          {candidates.map((c) => (
            <li key={c.id} className="flex flex-col gap-0.5 py-2.5 first:pt-0">
              <div className="flex items-baseline gap-2">
                <Link
                  href={`/w/${encodeURIComponent(workspaceId)}/settings/capabilities/skills/${String(c.itemId)}`}
                  className="truncate text-sm font-medium hover:underline"
                >
                  {c.name}
                </Link>
                <StatusChip
                  words={CANDIDATE_WORDS[c.status] ?? c.status}
                  tone={
                    c.status === "promoted"
                      ? "ok"
                      : c.status === "testing"
                        ? "busy"
                        : "off"
                  }
                />
                <span className="ml-auto shrink-0 text-xs text-ink-3 tabular-nums">
                  {c.status === "promoted"
                    ? `v${String(c.from)} → v${String(c.to ?? "?")}`
                    : `v${String(c.from)}`}
                  {c.score !== null &&
                    c.score !== undefined &&
                    ` · ${c.score.toFixed(2)} vs ${(c.baseScore ?? 0).toFixed(2)}`}
                </span>
              </div>
              <p className="text-xs text-pretty text-ink-2">{c.why}</p>
              {c.note && (
                <p className="text-xs text-pretty text-ink-3">{c.note}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}
