"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import type { Founder, FounderTask } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { DialogCloseButton } from "@/shared/ui/dialog";
import { Input } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { finishFounderTask, saveFounderTitle } from "./actions";

/** The Founder's initial: his name's, else his title's. */
export function founderInitial(founder: Founder): string {
  return (founder.name || founder.title).trim().charAt(0).toUpperCase() || "F";
}

/**
 * The card behind the Founder box: who he is (his name from Settings → General,
 * the title he gives himself here), the tasks only he can do (cards on Hermes's
 * Kanban assigned to him; the Co-Founder gives them) with Done, and the last done.
 */
export function FounderPanel({
  workspaceId,
  founder,
}: {
  workspaceId: string;
  founder: Founder;
}) {
  const [title, setTitle] = useState(founder.title);
  const [savedTitle, setSavedTitle] = useState(founder.title);
  const [error, setError] = useState<string | null>(null);
  const [finished, setFinished] = useState<Set<string>>(new Set());
  const [busy, start] = useTransition();
  const open = founder.open.filter((t) => !finished.has(t.id));

  const rename = () => {
    setError(null);
    start(async () => {
      const r = await saveFounderTitle(workspaceId, title);
      if (r.error) setError(r.error);
      else setSavedTitle(title.trim() || "Founder");
    });
  };

  const done = (task: FounderTask) => {
    setError(null);
    setFinished((s) => new Set(s).add(task.id));
    start(async () => {
      const r = await finishFounderTask(workspaceId, task.id);
      if (r.error) {
        setError(r.error);
        setFinished((s) => {
          const next = new Set(s);
          next.delete(task.id);
          return next;
        });
      }
    });
  };

  return (
    <div className="flex flex-col gap-5 p-6">
      <div className="flex items-start gap-3.5">
        <span className="grid size-12 shrink-0 place-items-center rounded-full bg-ink font-display text-lg font-semibold text-paper">
          {founderInitial(founder)}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="font-display text-lg leading-tight font-semibold text-balance text-ink">
            {founder.name || "You"}
          </h3>
          <p className="mt-0.5 text-sm text-ink-3">
            {savedTitle} · you, beside the Co-Founder.{" "}
            <Link
              href="/settings/general#your-name"
              className="underline underline-offset-2 hover:text-ink"
            >
              {founder.name ? "Change your name" : "Set your name"}
            </Link>
          </p>
        </div>
        <DialogCloseButton />
      </div>

      <form
        className="flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          rename();
        }}
      >
        <Input
          aria-label="Your title"
          value={title}
          maxLength={64}
          placeholder="Founder"
          onChange={(e) => {
            setTitle(e.target.value);
          }}
          className="h-9 flex-1"
        />
        <Button
          type="submit"
          disabled={busy || (title.trim() || "Founder") === savedTitle}
        >
          Rename
        </Button>
      </form>

      <section className="flex flex-col gap-2">
        <h4 className="text-sm font-medium text-ink">
          Your tasks{" "}
          <span className="text-ink-3 tabular-nums">({open.length})</span>
        </h4>
        <p className="text-sm text-pretty text-ink-2">
          What only a person can do — record, pay, sign, call, log in. The
          Co-Founder gives them to you; press Done (or tell it “salit”) and the
          cards waiting on it go on.
        </p>
        {open.length === 0 ? (
          <p className="rounded-xl bg-sunken px-3 py-2.5 text-sm text-ink-3">
            Nothing waits on you.
          </p>
        ) : (
          <ul className="flex flex-col divide-y divide-line rounded-xl border border-line">
            {open.map((task) => (
              <TaskRow
                key={task.id}
                workspaceId={workspaceId}
                task={task}
                busy={busy}
                onDone={() => {
                  done(task);
                }}
              />
            ))}
          </ul>
        )}
      </section>

      {founder.done.length + finished.size > 0 && (
        <section className="flex flex-col gap-2">
          <h4 className="text-sm font-medium text-ink">Done</h4>
          <ul className="flex flex-col gap-1 text-sm text-ink-3">
            {[
              ...founder.open.filter((t) => finished.has(t.id)),
              ...founder.done,
            ].map((task) => (
              <li key={task.id} className="flex min-w-0 items-center gap-2">
                <span aria-hidden className="text-live">
                  ✓
                </span>
                <Link
                  href={`/w/${workspaceId}/kanban?card=${encodeURIComponent(task.id)}`}
                  className="min-w-0 truncate hover:text-ink"
                >
                  {task.title}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
      <FormStatus error={error} />
    </div>
  );
}

function TaskRow({
  workspaceId,
  task,
  busy,
  onDone,
}: {
  workspaceId: string;
  task: FounderTask;
  busy: boolean;
  onDone: () => void;
}) {
  const unblocks = task.unblocks ?? [];
  const waitsOn = task.waitsOn ?? [];
  return (
    <li className="flex items-start gap-3 px-3 py-2.5">
      <div className="min-w-0 flex-1 [overflow-wrap:anywhere]">
        <Link
          href={`/w/${workspaceId}/kanban?card=${encodeURIComponent(task.id)}`}
          className="text-sm font-medium text-ink hover:underline"
        >
          {task.title}
        </Link>
        <p className="mt-0.5 text-xs text-ink-3">
          {task.canFinish
            ? unblocks.length > 0
              ? `Unblocks ${unblocks.join(", ")}`
              : "Yours to do"
            : `Waits on ${waitsOn.join(", ") || "other cards"} first`}
        </p>
      </div>
      <Button
        className="h-8 shrink-0"
        variant="primary"
        disabled={busy || !task.canFinish}
        onClick={onDone}
      >
        Done
      </Button>
    </li>
  );
}
