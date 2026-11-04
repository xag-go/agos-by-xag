"use client";

import { useEffect, useState, useTransition } from "react";
import type { CardDocOpen } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { Input, Textarea } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { Markdown } from "@/shared/ui/markdown";
import {
  annotateCardDoc,
  deleteAnnotation,
  openCardDoc,
  resolveAnnotation,
  restoreCardDoc,
  saveCardDoc,
} from "./doc-actions";
import { AnnotatedText, AnnotationRow, RevisionRow } from "./card-doc-text";

const label = "text-11 font-medium tracking-caps text-ink-3 uppercase";

type Mode = "read" | "rendered" | "edit";

export function OpenDocument({
  workspaceId,
  cardId,
  docKey,
}: {
  workspaceId: string;
  cardId: string;
  docKey: string;
}) {
  const [doc, setDoc] = useState<CardDocOpen | null | undefined>(undefined);
  const [mode, setMode] = useState<Mode>("read");
  const [busy, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const load = () => {
    start(async () => {
      const got = await openCardDoc(workspaceId, cardId, docKey);
      setDoc(got);
      setStale(false);
      setError(null);
    });
  };
  // One read per open (the list came with the card).
  useEffect(load, [workspaceId, cardId, docKey]);
  if (doc === undefined)
    return <p className="text-sm text-ink-3">Opening {docKey}.md…</p>;
  if (doc === null)
    return <p className="text-sm text-ink-3">This document is gone.</p>;
  const path = `/workspace/cards/${cardId}/${docKey}.md`;
  return (
    <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(0,1fr)_17rem]">
      <div className="flex min-h-0 flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2 text-xs text-ink-3">
          <span className="font-mono">{path}</span>
          <span>· v{doc.revision}</span>
          {doc.dirty && (
            <span className="rounded-md bg-attention px-1.5 py-0.5 text-attention-ink">
              written directly since v{doc.revision}
            </span>
          )}
          <span className="ml-auto flex gap-1">
            {(["read", "rendered", "edit"] as Mode[]).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => {
                  setMode(m);
                }}
                className={cn(
                  "rounded-md px-2 py-0.5 capitalize",
                  mode === m ? "bg-sunken text-ink" : "hover:text-ink",
                )}
              >
                {m === "read" ? "Comments" : m}
              </button>
            ))}
          </span>
        </div>
        {stale && (
          <div className="flex items-center gap-2 rounded-xl bg-attention/40 px-3 py-2 text-sm">
            Changed meanwhile: reload the document, then save again.
            <Button type="button" className="h-7 px-2 text-xs" onClick={load}>
              Reload
            </Button>
          </div>
        )}
        {mode === "edit" ? (
          <Editor
            doc={doc}
            busy={busy}
            onSave={(content, why) => {
              start(async () => {
                const r = await saveCardDoc(
                  workspaceId,
                  cardId,
                  docKey,
                  content,
                  why,
                  doc.revision,
                );
                if (r.stale) {
                  setStale(true);
                  setError(null);
                  return;
                }
                setError(r.error);
                if (!r.error) {
                  const got = await openCardDoc(workspaceId, cardId, docKey);
                  setDoc(got);
                  setMode("read");
                }
              });
            }}
          />
        ) : mode === "rendered" ? (
          <div className="min-h-0 flex-1 overflow-y-auto text-sm">
            <Markdown text={doc.content} />
          </div>
        ) : (
          <AnnotatedText
            doc={doc}
            busy={busy}
            onComment={(startAt, endAt, body) => {
              start(async () => {
                const r = await annotateCardDoc(
                  workspaceId,
                  cardId,
                  docKey,
                  startAt,
                  endAt,
                  body,
                );
                setError(r.error);
                if (r.annotation)
                  setDoc({
                    ...doc,
                    annotations: [...doc.annotations, r.annotation],
                  });
              });
            }}
          />
        )}
        <FormStatus error={error} />
      </div>
      <aside className="flex min-h-0 flex-col gap-5 overflow-y-auto text-sm">
        <section className="flex flex-col gap-2">
          <p className={label}>
            Comments · {doc.annotations.filter((a) => !a.resolved).length} open
          </p>
          {doc.annotations.length === 0 && (
            <p className="text-ink-3">
              Select a passage in Comments view to comment on it. The member
              sees open comments with the document.
            </p>
          )}
          {doc.annotations.map((a) => (
            <AnnotationRow
              key={a.id}
              annotation={a}
              busy={busy}
              onResolve={(resolved) => {
                start(async () => {
                  const r = await resolveAnnotation(
                    workspaceId,
                    cardId,
                    docKey,
                    a.id,
                    resolved,
                  );
                  setError(r.error);
                  if (!r.error)
                    setDoc({
                      ...doc,
                      annotations: doc.annotations.map((x) =>
                        x.id === a.id ? { ...x, resolved } : x,
                      ),
                    });
                });
              }}
              onDelete={() => {
                start(async () => {
                  const r = await deleteAnnotation(
                    workspaceId,
                    cardId,
                    docKey,
                    a.id,
                  );
                  setError(r.error);
                  if (!r.error)
                    setDoc({
                      ...doc,
                      annotations: doc.annotations.filter((x) => x.id !== a.id),
                    });
                });
              }}
            />
          ))}
        </section>
        <section className="flex flex-col gap-2">
          <p className={label}>Revisions · {doc.revisions.length}</p>
          {doc.revisions.map((r) => (
            <RevisionRow
              key={r.n}
              workspaceId={workspaceId}
              cardId={cardId}
              docKey={docKey}
              revision={r}
              current={r.n === doc.revision}
              busy={busy}
              onRestore={() => {
                start(async () => {
                  const res = await restoreCardDoc(
                    workspaceId,
                    cardId,
                    docKey,
                    r.n,
                  );
                  setError(res.error);
                  if (!res.error)
                    setDoc(await openCardDoc(workspaceId, cardId, docKey));
                });
              }}
            />
          ))}
        </section>
      </aside>
    </div>
  );
}

function Editor({
  doc,
  busy,
  onSave,
}: {
  doc: CardDocOpen;
  busy: boolean;
  onSave: (content: string, why: string) => void;
}) {
  const [content, setContent] = useState(doc.content);
  const [why, setWhy] = useState("");
  return (
    <form
      className="flex min-h-0 flex-1 flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        onSave(content, why.trim());
      }}
    >
      <Textarea
        aria-label="Document text"
        value={content}
        onChange={(e) => {
          setContent(e.currentTarget.value);
        }}
        className="min-h-[18rem] flex-1 font-mono text-xs leading-relaxed"
      />
      <div className="flex items-center gap-2">
        <Input
          aria-label="Why it changes"
          placeholder="Why it changes (one line, goes in CHANGES.md)"
          value={why}
          onChange={(e) => {
            setWhy(e.currentTarget.value);
          }}
          className="flex-1"
        />
        <Button
          type="submit"
          variant="primary"
          disabled={busy || content === doc.content}
        >
          {busy ? "Saving…" : `Save as v${doc.revision + 1}`}
        </Button>
      </div>
    </form>
  );
}
