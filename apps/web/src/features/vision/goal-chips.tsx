"use client";

import { cn } from "@/shared/ui/cn";
import { Select } from "@/shared/ui/field";
import { initials, percent, shown } from "./format";
import { type KeyResult, type Member, type Status } from "./goal-model";
import { STEP, TODO, small } from "./goal-styles";
import { unitFor } from "./goal-text";

export function StatusChip({ status }: { status: Status }) {
  if (status === "active") return null;
  return (
    <span
      className={cn(
        "shrink-0 rounded-full px-2 py-0.5 text-xs font-medium",
        status === "done"
          ? "bg-success-soft text-success"
          : status === "paused"
            ? "bg-hold-soft text-hold-ink"
            : "bg-sunken text-ink-3",
      )}
    >
      {status === "done" ? "Done" : status === "paused" ? "Paused" : "Dropped"}
    </span>
  );
}

export function OwnerSelect({
  value,
  members,
  disabled,
  onChange,
}: {
  value: string;
  members: Member[];
  disabled?: boolean;
  onChange: (owner: string) => void;
}) {
  return (
    <Select
      aria-label="Owner"
      className={cn(small, "!w-auto")}
      value={value}
      disabled={disabled}
      onChange={(e) => {
        onChange(e.target.value);
      }}
    >
      <option value="">Co-Founder</option>
      {members.map((m) => (
        <option key={m.name} value={m.name}>
          {m.title} (@{m.name})
        </option>
      ))}
    </Select>
  );
}

export function StatusSelect({
  value,
  disabled,
  onChange,
}: {
  value: Status;
  disabled?: boolean;
  onChange: (status: Status) => void;
}) {
  return (
    <Select
      aria-label="Status"
      className={cn(small, "!w-auto")}
      value={value}
      disabled={disabled}
      onChange={(e) => {
        onChange(e.target.value as Status);
      }}
    >
      <option value="active">Active</option>
      <option value="paused">Paused</option>
      <option value="done">Done</option>
      <option value="dropped">Dropped</option>
    </Select>
  );
}

/** “Not started”: a hollow dot and the words, quiet. */
function NotStarted() {
  return (
    <span className="inline-flex items-center gap-[5px] text-11.5 font-medium whitespace-nowrap text-ink-3 before:size-[7px] before:rounded-full before:border-[1.5px] before:border-goal-ns">
      Not started
    </span>
  );
}

/** The goal's overall percent as a small ring in its hue (or “Not started”). */
export function Ring({ pct }: { pct: number | null }) {
  const r = 24.5;
  const around = 2 * Math.PI * r;
  const share = Math.max(0, Math.min(100, pct ?? 0)) / 100;
  const none = pct === null || pct <= 0;
  return (
    <span
      className="relative block size-[54px] shrink-0"
      aria-label={none ? "Not started" : `${String(pct)}% overall`}
      role="img"
    >
      <svg
        aria-hidden
        width="54"
        height="54"
        viewBox="0 0 54 54"
        className="-rotate-90"
      >
        <circle
          cx="27"
          cy="27"
          r={r}
          fill="var(--panel)"
          stroke="var(--panel)"
          strokeWidth="5"
        />
        <circle
          cx="27"
          cy="27"
          r={r}
          fill="none"
          stroke="var(--goal-hue)"
          strokeOpacity="0.13"
          strokeWidth="5"
        />
        {!none && (
          <circle
            cx="27"
            cy="27"
            r={r}
            fill="none"
            stroke="var(--goal-hue)"
            strokeWidth="5"
            strokeLinecap="round"
            strokeDasharray={`${(around * share).toFixed(2)} ${around.toFixed(2)}`}
          />
        )}
      </svg>
      <span aria-hidden className="absolute inset-0 grid place-items-center">
        {none ? (
          <span className="text-center text-9.5 leading-heading font-medium text-ink-3">
            Not
            <br />
            started
          </span>
        ) : (
          <span className="font-vision-serif text-15 leading-none font-semibold text-ink tabular-nums">
            {String(pct)}
            <small className="ml-px font-sans text-10 text-ink-3">%</small>
          </span>
        )}
      </span>
    </span>
  );
}

export function KeyResultChip({
  result: k,
  onOpen,
}: {
  result: KeyResult;
  onOpen: () => void;
}) {
  const pct = percent(k.progress);
  const zero = pct === null || pct <= 0;
  return (
    <button
      type="button"
      aria-label={`${k.title}: ${shown(k.current)} of ${shown(k.target)}. Edit the goal`}
      title={k.source ? `${k.title} · source: ${k.source}` : k.title}
      className="flex min-w-0 flex-col rounded-14 bg-panel px-[13px] pt-[11px] pb-3 text-left shadow-goal transition-[translate,box-shadow] duration-150 hover:-translate-y-px hover:shadow-goal-lift"
      onClick={onOpen}
    >
      <span className="truncate text-12.5 font-semibold text-ink-2">
        {k.title}
      </span>
      <span className="mt-[7px] mb-[9px] flex min-w-0 items-baseline gap-[5px]">
        <b className="font-vision-serif text-19 leading-none font-semibold tracking-display text-ink tabular-nums">
          {shown(k.current)}
        </b>
        {k.target !== null && k.target !== undefined && (
          <span className="min-w-0 truncate text-xs text-ink-3 tabular-nums">
            / {shown(k.target)}
            {unitFor(k)}
          </span>
        )}
        <span className="ml-auto shrink-0 self-center">
          {zero ? (
            <NotStarted />
          ) : (
            <span className="rounded-full bg-goal-tint px-2 py-0.5 text-11.5 font-bold text-goal-hue tabular-nums">
              {String(pct)}%
            </span>
          )}
        </span>
      </span>
      <span className="goal-bar" data-zero={zero ? "" : undefined}>
        <i
          style={{ width: `${String(Math.max(0, Math.min(100, pct ?? 0)))}%` }}
        />
      </span>
    </button>
  );
}

export function Avatar({ name }: { name: string }) {
  return (
    <span
      aria-hidden
      className="inline-grid size-5 shrink-0 place-items-center rounded-full bg-goal-avatar text-8.5 font-bold tracking-label text-goal-avatar-ink"
    >
      {initials(name)}
    </span>
  );
}

export function StepPill({ status }: { status: string }) {
  const step = STEP[status] ?? TODO;
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-[5px] rounded-full px-2 py-[3px] text-11 font-semibold whitespace-nowrap before:size-[5px] before:rounded-full before:bg-current",
        step.tone,
      )}
    >
      {step.label}
    </span>
  );
}
