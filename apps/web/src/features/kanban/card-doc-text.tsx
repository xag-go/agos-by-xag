"use client";

import { useRef, useState, useTransition } from "react";
import type { CardDocAnnotation, CardDocOpen } from "@/data/types";
import { VoteButtons } from "@/features/feedback/vote-buttons";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { Textarea } from "@/shared/ui/field";
import { revisionText } from "./doc-actions";
import { dateTime } from "@/shared/format";

const when = (iso: string) => (iso ? dateTime(new Date(iso)) : "");

/**
 * The document's text with its comments marked on it (active: solid, stale:
 * dashed — the passage moved or changed a little, orphaned: struck — the passage
 * is gone). Selecting a passage offers a comment on it; the positions are the
 * selection's offsets in the text.
 */
export function AnnotatedText({
  doc,
  busy,
  onComment,
}: {
  doc: CardDocOpen;
  busy: boolean;
  onComment: (start: number, end: number, body: string) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [picked, setPicked] = useState<{ start: number; end: number } | null>(
    null,
  );
  const [body, setBody] = useState("");
  const onPick = () => {
    const sel = window.getSelection();
    const el = box.current;
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed || !el) return;
    const range = sel.getRangeAt(0);
    if (!el.contains(range.startContainer) || !el.contains(range.endContainer))
      return;
    const before = document.createRange();
    before.setStart(el, 0);
    before.setEnd(range.startContainer, range.startOffset);
    const start = before.toString().length;
    const end = start + range.toString().length;
    if (end > start) setPicked({ start, end });
  };
  const open = doc.annotations.filter((a) => !a.resolved);
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <div
        ref={box}
        onMouseUp={onPick}
        onKeyUp={onPick}
        className="min-h-0 flex-1 overflow-y-auto rounded-xl border border-line px-3 py-2 font-mono text-xs leading-relaxed whitespace-pre-wrap"
      >
        {segments(doc.content, open).map((s, i) =>
          s.marks.length === 0 ? (
            <span key={i}>{s.text}</span>
          ) : (
            <mark
              key={i}
              title={s.marks.map((m) => m.body).join("\n")}
              className={cn(
                "rounded-sm bg-transparent text-ink",
                s.marks.some((m) => m.anchor === "active") &&
                  "bg-accent-soft underline decoration-accent decoration-2",
                s.marks.every((m) => m.anchor !== "active") &&
                  s.marks.some((m) => m.anchor === "stale") &&
                  "bg-attention/40 underline decoration-dashed decoration-attention-ink",
                s.marks.every((m) => m.anchor === "orphaned") &&
                  "text-ink-3 line-through decoration-line-strong",
              )}
            >
              {s.text}
            </mark>
          ),
        )}
      </div>
      {picked && (
        <form
          className="flex flex-col gap-2 rounded-xl border border-line bg-panel p-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (!body.trim()) return;
            onComment(picked.start, picked.end, body.trim());
            setPicked(null);
            setBody("");
          }}
        >
          <p className="line-clamp-2 text-xs text-ink-3">
            “{doc.content.slice(picked.start, picked.end)}”
          </p>
          <Textarea
            rows={2}
            autoFocus
            aria-label="Your comment on this passage"
            placeholder="Your comment on this passage (the member reads it)"
            value={body}
            onChange={(e) => {
              setBody(e.currentTarget.value);
            }}
          />
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setPicked(null);
                setBody("");
              }}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              disabled={busy || !body.trim()}
            >
              Comment
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}

type Segment = { text: string; marks: CardDocAnnotation[] };

/** The text cut where a comment starts or ends, each piece with its comments. */
function segments(text: string, marks: CardDocAnnotation[]): Segment[] {
  const cuts = new Set<number>([0, text.length]);
  for (const m of marks) {
    cuts.add(Math.max(0, Math.min(text.length, m.start)));
    cuts.add(Math.max(0, Math.min(text.length, m.end)));
  }
  const points = [...cuts].sort((a, b) => a - b);
  const out: Segment[] = [];
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i] ?? 0;
    const b = points[i + 1] ?? a;
    if (b <= a) continue;
    out.push({
      text: text.slice(a, b),
      marks: marks.filter((m) => m.start <= a && m.end >= b),
    });
  }
  return out;
}

export function AnnotationRow({
  annotation: a,
  busy,
  onResolve,
  onDelete,
}: {
  annotation: CardDocAnnotation;
  busy: boolean;
  onResolve: (resolved: boolean) => void;
  onDelete: () => void;
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-1 rounded-xl border border-line px-2.5 py-2",
        a.resolved && "opacity-60",
      )}
    >
      <p className="line-clamp-2 text-xs text-ink-3 italic">“{a.quote}”</p>
      <p className="text-sm">{a.body}</p>
      <p className="flex flex-wrap items-center gap-1.5 text-xs text-ink-3">
        <span>{a.author}</span>
        <span>· v{a.revision}</span>
        {!a.resolved && a.anchor !== "active" && (
          <span
            className={cn(
              "rounded-md px-1 py-0.5",
              a.anchor === "stale"
                ? "bg-attention text-attention-ink"
                : "bg-sunken text-ink-3",
            )}
          >
            {a.anchor === "stale" ? "passage changed" : "passage gone"}
          </span>
        )}
        <span className="ml-auto flex gap-2">
          <button
            type="button"
            disabled={busy}
            className="hover:text-ink"
            onClick={() => {
              onResolve(!a.resolved);
            }}
          >
            {a.resolved ? "Reopen" : "Resolve"}
          </button>
          <button
            type="button"
            disabled={busy}
            aria-label="Delete comment"
            className="hover:text-danger"
            onClick={onDelete}
          >
            ✕
          </button>
        </span>
      </p>
    </div>
  );
}

export function RevisionRow({
  workspaceId,
  cardId,
  docKey,
  revision: r,
  current,
  busy,
  onRestore,
}: {
  workspaceId: string;
  cardId: string;
  docKey: string;
  revision: CardDocOpen["revisions"][number];
  current: boolean;
  busy: boolean;
  onRestore: () => void;
}) {
  const [diff, setDiff] = useState<string | null>(null);
  const [, start] = useTransition();
  return (
    <div className="flex flex-col gap-1 rounded-xl border border-line px-2.5 py-2">
      <p className="flex items-center gap-1.5 text-xs">
        <span className="font-medium text-ink">v{r.n}</span>
        <span className="text-ink-3">· {r.who}</span>
        <span className="ml-auto text-ink-3" title={when(r.at)}>
          {when(r.at)}
        </span>
      </p>
      {r.why && <p className="text-xs text-ink-2">{r.why}</p>}
      <div className="flex items-center gap-2 text-xs">
        <VoteButtons
          key={`${String(r.n)}:${String(r.vote)}`}
          workspaceId={workspaceId}
          kind="revision"
          target={`${cardId}:${docKey}:${String(r.n)}`}
          vote={r.vote}
          subject={`${docKey}.md v${String(r.n)} (${r.why})`}
        />
        <button
          type="button"
          className="text-ink-3 hover:text-ink"
          onClick={() => {
            if (diff !== null) {
              setDiff(null);
              return;
            }
            start(async () => {
              const got = await revisionText(workspaceId, cardId, docKey, r.n);
              setDiff(got?.diff ?? "(no diff)");
            });
          }}
        >
          {diff === null ? "Changes" : "Hide"}
        </button>
        {!current && (
          <button
            type="button"
            disabled={busy}
            className="text-ink-3 hover:text-ink"
            onClick={onRestore}
          >
            Restore
          </button>
        )}
      </div>
      {diff !== null && (
        <pre className="max-h-48 overflow-auto rounded-lg bg-sunken px-2 py-1 font-mono text-11 leading-snug whitespace-pre-wrap">
          {diff || "(no changes against the one before)"}
        </pre>
      )}
    </div>
  );
}
