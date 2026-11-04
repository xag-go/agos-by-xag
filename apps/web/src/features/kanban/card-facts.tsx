"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import type { KanbanBoard, KanbanCardDetail } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { Select } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { attachToCard, estimateCard, removeCardFile } from "./card-actions";
import { setCardLabels, watchCard } from "./board-actions";
import { labelClass, LabelChips, type BoardLabel } from "./labels";
import { ago, fmtTokens, when } from "./card-format";
import { toBase64 } from "@/shared/files";

export function CardFacts({
  workspaceId,
  card,
}: {
  workspaceId: string;
  card: KanbanCardDetail;
}) {
  const [busy, start] = useTransition();
  const [estimate, setEstimate] = useState<{
    tokens: number;
    complexity: string;
    why: string;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const files = card.attachments ?? [];
  const label = "text-11 font-medium tracking-caps text-ink-3 uppercase";
  return (
    <div className="flex flex-col gap-5 text-sm">
      <div>
        <p className={label}>Created by</p>
        <p className="mt-1 text-ink-2">{card.createdBy || "You"}</p>
      </div>
      <div>
        <p className={label}>Created</p>
        <p className="mt-1 text-ink-2" title={when(card.createdAt)}>
          {ago(card.createdAt)}
        </p>
      </div>
      <div>
        <p className={label}>Estimate</p>
        {estimate ? (
          <p className="mt-1 text-ink-2">
            {estimate.complexity && (
              <span className="mr-1.5 rounded-md bg-sunken px-1.5 py-0.5 text-xs font-medium">
                {estimate.complexity}
              </span>
            )}
            {fmtTokens(estimate.tokens)}
            {estimate.why && (
              <span className="mt-1 block text-xs text-ink-3">
                {estimate.why}
              </span>
            )}
          </p>
        ) : (
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <Button
              type="button"
              disabled={busy}
              onClick={() => {
                start(async () => {
                  const res = await estimateCard(workspaceId, card.id);
                  setError(res.error);
                  if (res.estimate) setEstimate(res.estimate);
                });
              }}
            >
              {busy ? "Estimating…" : "Estimate effort"}
            </Button>
            <span className="text-xs text-ink-3">makes a model call</span>
          </div>
        )}
        <FormStatus error={error} />
      </div>
      <div>
        <div className="flex items-center justify-between">
          <p className={label}>Attachments · {files.length}</p>
          <label className="cursor-pointer text-xs text-ink-2 underline">
            Add
            <input
              type="file"
              className="sr-only"
              disabled={busy}
              onChange={(e) => {
                const file = e.currentTarget.files?.[0];
                e.currentTarget.value = "";
                if (!file) return;
                start(async () => {
                  const data = await toBase64(file);
                  setError(
                    (await attachToCard(workspaceId, card.id, file.name, data))
                      .error,
                  );
                });
              }}
            />
          </label>
        </div>
        {files.length === 0 ? (
          <p className="mt-1 text-ink-3">No attachments yet.</p>
        ) : (
          <ul className="mt-1 flex flex-col gap-1">
            {files.map((f) => (
              <li key={f.id} className="flex items-center gap-2">
                <a
                  href={`/api/w/${encodeURIComponent(workspaceId)}/kanban/${encodeURIComponent(card.id)}/files/${String(f.id)}`}
                  className="min-w-0 flex-1 truncate underline"
                >
                  {f.name}
                </a>
                <button
                  type="button"
                  aria-label={`Remove ${f.name}`}
                  disabled={busy}
                  className="text-xs text-ink-3 hover:text-danger"
                  onClick={() => {
                    start(async () => {
                      setError(
                        (await removeCardFile(workspaceId, card.id, f.id))
                          .error,
                      );
                    });
                  }}
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

const SECTION = "text-11 font-medium tracking-caps text-ink-3 uppercase";

/** The card's labels (the workspace's, picked here; a block in its Hermes body). */
export function CardLabels({
  workspaceId,
  card,
  labels,
  busy,
  run,
}: {
  workspaceId: string;
  card: KanbanCardDetail;
  labels: BoardLabel[];
  busy: boolean;
  run: (task: () => Promise<{ error: string | null }>) => void;
}) {
  const [open, setOpen] = useState(false);
  const mine = card.labels ?? [];
  return (
    <section className="flex flex-col gap-2">
      <p className={SECTION}>Labels</p>
      <LabelChips ids={mine} labels={labels} />
      {labels.length === 0 ? (
        <Link
          href={`/w/${encodeURIComponent(workspaceId)}/settings/labels`}
          className="text-xs text-ink-3 hover:text-ink"
        >
          Make labels in Settings → Labels
        </Link>
      ) : (
        <>
          <Button
            variant="ghost"
            className="self-start"
            aria-expanded={open}
            onClick={() => {
              setOpen(!open);
            }}
          >
            {open ? "Close" : mine.length > 0 ? "Change labels" : "Add labels"}
          </Button>
          {open && (
            <div className="flex flex-wrap gap-1">
              {labels.map((l) => {
                const on = mine.includes(l.id);
                return (
                  <button
                    key={l.id}
                    type="button"
                    aria-pressed={on}
                    disabled={busy}
                    className={cn(
                      "rounded-md border px-1.5 py-0.5 text-xs",
                      on ? "border-ink" : "border-transparent opacity-70",
                      labelClass(l.color),
                    )}
                    onClick={() => {
                      run(() =>
                        setCardLabels(
                          workspaceId,
                          card.id,
                          on ? mine.filter((x) => x !== l.id) : [...mine, l.id],
                        ),
                      );
                    }}
                  >
                    {l.folder ? `${l.folder} / ` : ""}
                    {l.name}
                  </button>
                );
              })}
            </div>
          )}
        </>
      )}
    </section>
  );
}

/** Who follows the card (Hermes's notify subscriptions): add or remove one. */
export function Watchers({
  workspaceId,
  card,
  members,
  busy,
  run,
}: {
  workspaceId: string;
  card: KanbanCardDetail;
  members: KanbanBoard["members"];
  busy: boolean;
  run: (task: () => Promise<{ error: string | null }>) => void;
}) {
  const watchers = card.watchers ?? [];
  const names = new Set(watchers.map((w) => w.name));
  return (
    <section className="flex flex-col gap-2">
      <p className={SECTION}>Following</p>
      {watchers.length === 0 ? (
        <p className="text-xs text-ink-3">Nobody yet.</p>
      ) : (
        <ul className="flex flex-wrap gap-1">
          {watchers.map((w) => (
            <li
              key={`${w.name}-${w.title}`}
              className="inline-flex items-center gap-1 rounded-md bg-sunken px-1.5 py-0.5 text-xs text-ink-2"
              title={
                w.mode === "notify" ? "Hears its news" : "Woken by its news"
              }
            >
              {w.title}
              {w.name && (
                <button
                  type="button"
                  aria-label={`Stop ${w.title} following`}
                  disabled={busy}
                  className="text-ink-3 hover:text-ink"
                  onClick={() => {
                    run(() => watchCard(workspaceId, card.id, w.name, false));
                  }}
                >
                  ×
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      <Select
        aria-label="Add a follower"
        value=""
        disabled={busy}
        onChange={(e) => {
          const who = e.currentTarget.value;
          if (who) run(() => watchCard(workspaceId, card.id, who, true));
        }}
      >
        <option value="">Add a follower…</option>
        {members
          .filter((m) => !names.has(m.name) && m.name !== "founder")
          .map((m) => (
            <option key={m.name} value={m.name}>
              {m.title}
            </option>
          ))}
      </Select>
    </section>
  );
}
