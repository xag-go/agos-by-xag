"use client";

import { useState, useTransition } from "react";
import type { StatusCard, StatusPage } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { useAsk } from "@/shared/ui/confirm";
import { Field, Input, Select } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { Markdown } from "@/shared/ui/markdown";
import { formatWhen } from "@/shared/format";
import {
  addStatusCard,
  deleteStatusCard,
  refreshStatusCard,
  saveStatusCard,
  statusRevision,
  type StatusCardFields,
} from "./actions";
import { PANEL } from "@/shared/ui/panel";

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function policyText(card: StatusCard): string {
  if (card.policy === "manual") return "When you ask";
  if (card.policy === "weekly")
    return `Weekly, ${DAYS[card.day ?? 1] ?? "Mon"} ${card.time}`;
  return `Daily, ${card.time}`;
}

/** The new-card / edit form: title, what it covers, how often. */
function CardForm({
  workspaceId,
  page,
  card,
  onDone,
}: {
  workspaceId: string;
  page: StatusPage;
  card?: StatusCard;
  onDone: () => void;
}) {
  const [fields, setFields] = useState<StatusCardFields>({
    title: card?.title ?? "",
    scope: card?.scope ?? "workspace",
    scopeRef: card?.scopeRef ?? "",
    policy: card?.policy ?? "daily",
    time: card?.time ?? "08:00",
    day: card?.day ?? 1,
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  const set = (change: Partial<StatusCardFields>) => {
    setFields((was) => ({ ...was, ...change }));
  };
  const goals = page.plan.filter((p) => p.level === "goal");
  const projects = page.plan.filter((p) => p.level === "project");
  return (
    <form
      className={`${PANEL} grid gap-3 px-4 py-3 sm:grid-cols-2`}
      onSubmit={(event) => {
        event.preventDefault();
        start(async () => {
          const r = card
            ? await saveStatusCard(workspaceId, card.id, fields)
            : await addStatusCard(workspaceId, fields);
          setError(r.error);
          if (!r.error) onDone();
        });
      }}
    >
      <Field label="Title" className="sm:col-span-2">
        <Input
          value={fields.title}
          maxLength={120}
          placeholder="Spring launch, Content team…"
          onChange={(e) => {
            set({ title: e.target.value });
          }}
        />
      </Field>
      <Field label="Covers">
        <Select
          value={fields.scope}
          onChange={(e) => {
            set({
              scope: e.target.value as StatusCardFields["scope"],
              scopeRef: "",
            });
          }}
        >
          <option value="workspace">The whole workspace</option>
          <option value="goal">A goal</option>
          <option value="project">A project</option>
          <option value="member">A member&apos;s cards</option>
          <option value="query">Cards with some words</option>
        </Select>
      </Field>
      {fields.scope === "workspace" ? (
        <div />
      ) : fields.scope === "query" ? (
        <Field label="Words" hint="Cards whose title or text has every word.">
          <Input
            value={fields.scopeRef}
            maxLength={200}
            onChange={(e) => {
              set({ scopeRef: e.target.value });
            }}
          />
        </Field>
      ) : (
        <Field
          label={
            fields.scope === "member"
              ? "Member"
              : fields.scope === "goal"
                ? "Goal"
                : "Project"
          }
        >
          <Select
            value={fields.scopeRef}
            onChange={(e) => {
              set({ scopeRef: e.target.value });
            }}
          >
            <option value="">Pick one</option>
            {fields.scope === "member"
              ? page.members.map((m) => (
                  <option key={m.name} value={m.name}>
                    {m.title} (@{m.name})
                  </option>
                ))
              : (fields.scope === "goal" ? goals : projects).map((p) => (
                  <option key={p.id} value={String(p.id)}>
                    {p.title}
                  </option>
                ))}
          </Select>
        </Field>
      )}
      <Field
        label="Updates"
        hint="The Co-Founder writes only when something changed (or you ask)."
      >
        <Select
          value={fields.policy}
          onChange={(e) => {
            set({ policy: e.target.value as StatusCardFields["policy"] });
          }}
        >
          <option value="daily">Daily</option>
          <option value="weekly">Weekly</option>
          <option value="manual">When I ask</option>
        </Select>
      </Field>
      {fields.policy === "manual" ? (
        <div />
      ) : (
        <div className="flex gap-2">
          {fields.policy === "weekly" && (
            <Field label="Day">
              <Select
                value={String(fields.day ?? 1)}
                onChange={(e) => {
                  set({ day: Number(e.target.value) });
                }}
              >
                {DAYS.map((d, i) => (
                  <option key={d} value={String(i)}>
                    {d}
                  </option>
                ))}
              </Select>
            </Field>
          )}
          <Field label="Time (your timezone)">
            <Input
              type="time"
              value={fields.time}
              onChange={(e) => {
                set({ time: e.target.value });
              }}
            />
          </Field>
        </div>
      )}
      <div className="flex items-center gap-2 sm:col-span-2">
        <Button type="submit" variant="primary" disabled={busy}>
          {card ? "Save" : "Add the card"}
        </Button>
        <Button variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <FormStatus error={error} />
      </div>
    </form>
  );
}

function CardView({
  workspaceId,
  page,
  card,
}: {
  workspaceId: string;
  page: StatusPage;
  card: StatusCard;
}) {
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  const [shown, setShown] = useState<{ n: number; content: string } | null>(
    null,
  );
  const { dialog, confirm } = useAsk();
  if (editing)
    return (
      <CardForm
        workspaceId={workspaceId}
        page={page}
        card={card}
        onDone={() => {
          setEditing(false);
        }}
      />
    );
  const asked =
    card.refreshAskedAt &&
    (!card.writtenAt || card.refreshAskedAt > card.writtenAt);
  return (
    <article
      id={`card-${String(card.id)}`}
      className={`${PANEL} flex scroll-mt-6 flex-col gap-3 px-4 py-3 target:border-accent`}
    >
      {dialog}
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="font-display text-base font-semibold text-ink">
            {card.title}
          </p>
          <p className="text-xs text-ink-3">
            {card.scopeLabel} · {policyText(card)}
            {card.revision > 0 &&
              ` · v${String(card.revision)} by ${card.writtenBy}, ${formatWhen(card.writtenAt)}`}
          </p>
        </div>
        <Button
          disabled={busy || Boolean(asked)}
          onClick={() => {
            start(async () => {
              setError((await refreshStatusCard(workspaceId, card.id)).error);
            });
          }}
        >
          {asked ? "Refresh asked…" : "Refresh now"}
        </Button>
        <Button
          variant="ghost"
          onClick={() => {
            setEditing(true);
          }}
        >
          Edit
        </Button>
        <Button
          variant="ghost"
          disabled={busy}
          onClick={() => {
            void (async () => {
              const yes = await confirm({
                title: `Remove “${card.title}”?`,
                body: "Its Co-Founder job stops. Its summaries stay in the workspace folder.",
                confirmLabel: "Remove",
                danger: true,
              });
              if (!yes) return;
              start(async () => {
                setError((await deleteStatusCard(workspaceId, card.id)).error);
              });
            })();
          }}
        >
          Remove
        </Button>
      </div>
      {shown ? (
        <div className="rounded-lg border border-dashed border-line px-3 py-2">
          <p className="mb-1 text-xs text-ink-3">
            Revision v{String(shown.n)} ·{" "}
            <button
              type="button"
              className="underline"
              onClick={() => {
                setShown(null);
              }}
            >
              back to the latest
            </button>
          </p>
          <Markdown text={shown.content} className="text-sm" />
        </div>
      ) : card.summary ? (
        <Markdown text={card.summary} className="text-sm" />
      ) : (
        <p className="text-sm text-ink-3">
          No summary yet. The Co-Founder writes the first one at the next
          update, or now with Refresh now.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2 text-xs text-ink-3">
        {card.revisions.length > 1 && (
          <Select
            className="h-8 w-auto text-xs"
            value={shown ? String(shown.n) : ""}
            onChange={(e) => {
              const n = Number(e.target.value);
              if (!n || n === card.revision) {
                setShown(null);
                return;
              }
              start(async () => {
                const r = await statusRevision(workspaceId, card.id, n);
                if ("error" in r) setError(r.error);
                else setShown({ n, content: r.content });
              });
            }}
          >
            <option value="">
              Revisions ({String(card.revisions.length)})
            </option>
            {card.revisions.map((r) => (
              <option key={r.n} value={String(r.n)}>
                v{String(r.n)} · {r.who} · {formatWhen(r.at)} · {r.why}
              </option>
            ))}
          </Select>
        )}
        {card.job?.nextAt && card.policy !== "manual" && (
          <span>Next check {formatWhen(card.job.nextAt)}</span>
        )}
        {card.job?.changedAt && (
          <span>Scope last changed {formatWhen(card.job.changedAt)}</span>
        )}
        {card.job?.problem && (
          <span className="text-danger">{card.job.problem}</span>
        )}
        {!card.job && (
          <span className="text-ink-2">
            Its Co-Founder job isn&apos;t set up yet (the engine was off): save
            the card again.
          </span>
        )}
      </div>
      <FormStatus error={error} />
    </article>
  );
}

/** Status cards: a scope of the workspace and the Co-Founder's short summary of
 * it, kept up to date daily, weekly or when the owner asks; every summary is
 * kept as a revision. */
export function StatusView({
  workspaceId,
  page,
}: {
  workspaceId: string;
  page: StatusPage;
}) {
  const [adding, setAdding] = useState(page.cards.length === 0);
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <p className="max-w-2xl text-sm text-ink-2">
          Each card follows one part of the work (the whole workspace, a goal, a
          project, a member, or cards with some words). The Co-Founder writes
          its short summary on the schedule you pick, only when something in it
          changed, so a quiet day costs nothing.
        </p>
        {!adding && (
          <Button
            variant="primary"
            onClick={() => {
              setAdding(true);
            }}
          >
            New status card
          </Button>
        )}
      </div>
      {adding && (
        <CardForm
          workspaceId={workspaceId}
          page={page}
          onDone={() => {
            setAdding(false);
          }}
        />
      )}
      <div
        className={cn("grid gap-4", page.cards.length > 1 && "xl:grid-cols-2")}
      >
        {page.cards.map((card) => (
          <CardView
            key={card.id}
            workspaceId={workspaceId}
            page={page}
            card={card}
          />
        ))}
      </div>
    </div>
  );
}
