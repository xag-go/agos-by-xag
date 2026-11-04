"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import type { NotesRevisionText, Organized, VisionNotes } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { Textarea } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { notesRevision, organizeNotes, saveNotes } from "./actions";
import { dateTime, plural } from "@/shared/format";

/** What Organize found, for the Vision form above the goals (not saved yet). */
export type VisionPreview = Pick<Organized, "vision" | "why" | "strategy">;

function when(at: string | null | undefined): string {
  if (!at) return "";
  const date = new Date(at);
  return Number.isNaN(date.getTime()) ? at : dateTime(date);
}

/** The owner's free notes at the top of the Vision page: anything, in any
 * language. Organize has the Co-Founder turn them into the Vision, Why and
 * Strategy (a preview he edits and saves) and proposes the goals it found in
 * his Inbox. Once the Vision is set, saved notes start folded to one line. */
export function NotesBox({
  workspaceId,
  notes,
  folded = false,
  onOrganized,
}: {
  workspaceId: string;
  notes: VisionNotes | null;
  /** Start as one line (the Vision is set: the notes sit at the bottom). */
  folded?: boolean;
  onOrganized: (preview: VisionPreview) => void;
}) {
  const saved = notes?.text ?? "";
  const foldable = folded;
  const [open, setOpen] = useState(!foldable);
  const [text, setText] = useState(saved);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Organized | null>(null);
  const [old, setOld] = useState<NotesRevisionText | null>(null);
  const [saving, startSave] = useTransition();
  const [organizing, startOrganize] = useTransition();
  const busy = saving || organizing;
  const dirty = text.trim() !== saved.trim();
  const revisions = notes?.revisions ?? [];
  const lines = saved.trimEnd().split("\n").length;

  if (!open)
    return (
      <button
        type="button"
        className="flex min-h-12 min-w-0 flex-1 basis-[20rem] items-center gap-2.5 rounded-14 bg-panel/75 px-5 py-3 text-left text-13.5 font-semibold text-ink-2 shadow-vision-card transition-colors hover:bg-panel"
        aria-expanded={false}
        aria-label="Open your notes"
        onClick={() => {
          setOpen(true);
        }}
      >
        <span aria-hidden className="text-xs text-ink-3">
          ▸
        </span>
        Your notes
        <span className="ml-auto min-w-0 truncate text-12.5 font-normal text-ink-3 tabular-nums">
          {saved.trim() === ""
            ? "Write here, then Organize"
            : notes?.updatedAt
              ? `saved ${when(notes.updatedAt)}`
              : plural(lines, "line")}
        </span>
      </button>
    );

  return (
    <section
      aria-label="Your notes"
      className="vision-card flex basis-full flex-col gap-3 px-6 py-5"
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="text-sm font-semibold">Your notes</h2>
        <p className="min-w-0 flex-1 text-xs text-ink-3">
          {notes && notes.revision > 0
            ? `Saved · v${String(notes.revision)} · ${when(notes.updatedAt)}`
            : "Not saved yet"}
          {dirty && " · unsaved changes"}
        </p>
        {foldable && (
          <Button
            variant="ghost"
            className="h-8 px-2.5 text-xs"
            aria-expanded
            disabled={organizing}
            onClick={() => {
              setOpen(false);
            }}
          >
            Close
          </Button>
        )}
      </div>
      <p className="text-xs text-ink-3">
        Write everything here, in any language and in any order: why you
        started, where you want to go, ideas, numbers. Organize turns it into
        the Vision, Why and Strategy (in English) and proposes the goals it
        finds in your Inbox.
      </p>
      <Textarea
        rows={8}
        value={text}
        maxLength={30_000}
        aria-label="Your notes"
        placeholder="I want to…"
        disabled={organizing}
        onChange={(e) => {
          setText(e.target.value);
        }}
      />
      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="primary"
          disabled={busy || !text.trim()}
          onClick={() => {
            setError(null);
            setResult(null);
            startOrganize(async () => {
              const r = await organizeNotes(workspaceId, text);
              setError(r.error);
              if (r.organized) {
                setResult(r.organized);
                onOrganized(r.organized);
              }
            });
          }}
        >
          {organizing ? (
            <span className="flex items-center gap-2">
              <span
                aria-hidden
                className="size-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"
              />
              Organizing…
            </span>
          ) : (
            "Organize"
          )}
        </Button>
        <Button
          variant="ghost"
          disabled={busy || !dirty}
          onClick={() => {
            setError(null);
            startSave(async () => {
              const r = await saveNotes(workspaceId, text);
              setError(r.error);
            });
          }}
        >
          {saving ? "Saving…" : "Save notes"}
        </Button>
        {organizing && (
          <span className="text-xs text-ink-3">
            The Co-Founder is reading your notes. This takes 10 to 40 seconds.
          </span>
        )}
        <FormStatus error={error} />
      </div>
      {result && <OrganizedNote workspaceId={workspaceId} result={result} />}
      {revisions.length > 1 && (
        <details className="text-xs text-ink-2">
          <summary className="cursor-pointer text-ink-3">
            Earlier versions ({revisions.length})
          </summary>
          <ul className="mt-2 flex flex-col gap-1">
            {revisions.map((r) => (
              <li key={r.n} className="flex items-center gap-2">
                <button
                  type="button"
                  className="underline"
                  disabled={busy}
                  onClick={() => {
                    void (async () => {
                      const found = await notesRevision(workspaceId, r.n);
                      setError(found.error);
                      setOld(found.revision ?? null);
                    })();
                  }}
                >
                  v{r.n}
                </button>
                <span className="text-ink-3">{when(r.at)}</span>
              </li>
            ))}
          </ul>
          {old && (
            <div className="mt-2 flex flex-col gap-2 rounded-lg bg-sunken/60 px-3 py-2">
              <pre className="max-h-60 overflow-auto font-sans text-sm whitespace-pre-wrap text-ink">
                {old.content}
              </pre>
              <div className="flex gap-2">
                <Button
                  variant="ghost"
                  onClick={() => {
                    setText(old.content.replace(/\n$/, ""));
                    setOld(null);
                  }}
                >
                  Use this version
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => {
                    setOld(null);
                  }}
                >
                  Close
                </Button>
              </div>
            </div>
          )}
        </details>
      )}
    </section>
  );
}

function OrganizedNote({
  workspaceId,
  result,
}: {
  workspaceId: string;
  result: Organized;
}) {
  const found = result.goals?.length ?? 0;
  const inbox = `/w/${encodeURIComponent(workspaceId)}/inbox`;
  return (
    <div className="flex flex-col gap-1 rounded-lg bg-sunken/60 px-3 py-2 text-sm text-ink-2">
      <p>
        The Vision, Why and Strategy below are filled from your notes. They are
        not saved yet: edit them, then Save.
      </p>
      {result.proposed > 0 && (
        <p>
          {plural(result.proposed, "goal")} proposed in your{" "}
          <Link className="underline" href={inbox}>
            Inbox
          </Link>
          .
        </p>
      )}
      {result.already > 0 && (
        <p>
          {plural(result.already, "goal")} already waiting in your{" "}
          <Link className="underline" href={inbox}>
            Inbox
          </Link>
          .
        </p>
      )}
      {result.waiting > 0 && (
        <p>
          {plural(result.waiting, "goal")} will go to your Inbox when you save
          the Vision.
        </p>
      )}
      {found === 0 && <p>No goals found in the notes.</p>}
      {(result.problems ?? []).map((p) => (
        <p key={p} className="text-danger">
          Not proposed: {p}
        </p>
      ))}
    </div>
  );
}
