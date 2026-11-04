"use client";

import { useState, useTransition } from "react";
import type { KanbanCardDetail } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { Input } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { saveCardDoc } from "./doc-actions";
import { OpenDocument } from "./card-doc-open";

/**
 * The card's documents: files under cards/<card>/ in the workspace folder (the
 * members read and write them there), one revision per save. The list comes
 * with the card; a document's text, revisions and passage comments are read when
 * it is opened. A save carries the revision that was opened: when the document
 * moved meanwhile the core refuses it and the editor says to reload.
 */
export function DocumentsTab({
  workspaceId,
  card,
  initialKey,
}: {
  workspaceId: string;
  card: KanbanCardDetail;
  initialKey?: string;
}) {
  const docs = card.documents ?? [];
  const [key, setKey] = useState<string | null>(
    initialKey && docs.some((d) => d.key === initialKey)
      ? initialKey
      : (docs[0]?.key ?? null),
  );
  const [adding, setAdding] = useState(docs.length === 0);
  const [newKey, setNewKey] = useState("");
  // The documents' last revisions, as the card came: a different stamp reloads
  // the open one (a member saved while the card was open).
  const stamp = docs.map((d) => `${d.key}@${String(d.revision)}`).join(",");
  return (
    <div className="flex h-full min-h-[24rem] flex-col gap-3">
      <div className="flex flex-wrap items-center gap-1.5">
        {docs.map((d) => (
          <button
            key={d.key}
            type="button"
            onClick={() => {
              setKey(d.key);
              setAdding(false);
            }}
            className={cn(
              "flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-sm",
              d.key === key && !adding
                ? "border-ink bg-sunken text-ink"
                : "border-line text-ink-2 hover:border-line-strong",
            )}
          >
            <span className="font-mono">{d.key}.md</span>
            <span className="text-xs text-ink-3">v{d.revision}</span>
            {d.openAnnotations > 0 && (
              <span className="rounded-md bg-attention px-1 text-11 text-attention-ink">
                {d.openAnnotations}
              </span>
            )}
          </button>
        ))}
        <Button
          type="button"
          variant="ghost"
          className="h-8 px-2 text-xs"
          onClick={() => {
            setAdding(true);
          }}
        >
          + New document
        </Button>
      </div>
      {adding ? (
        <NewDocument
          workspaceId={workspaceId}
          cardId={card.id}
          value={newKey}
          onChange={setNewKey}
          onDone={(made) => {
            setAdding(false);
            setNewKey("");
            setKey(made);
          }}
          onCancel={docs.length > 0 ? () => setAdding(false) : undefined}
        />
      ) : key ? (
        <OpenDocument
          key={`${key}:${stamp}`}
          workspaceId={workspaceId}
          cardId={card.id}
          docKey={key}
        />
      ) : null}
    </div>
  );
}

function NewDocument({
  workspaceId,
  cardId,
  value,
  onChange,
  onDone,
  onCancel,
}: {
  workspaceId: string;
  cardId: string;
  value: string;
  onChange: (v: string) => void;
  onDone: (key: string) => void;
  onCancel?: () => void;
}) {
  const [busy, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  return (
    <form
      className="flex max-w-prose flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        const key = value.trim().replace(/\.md$/, "");
        if (!key) return;
        start(async () => {
          const r = await saveCardDoc(
            workspaceId,
            cardId,
            key,
            `# ${key}\n\n`,
            "created",
            null,
          );
          setError(r.error);
          if (!r.error) onDone(key);
        });
      }}
    >
      <p className="text-sm text-ink-2">
        A document is a markdown file of this card, at{" "}
        <span className="font-mono text-xs">
          /workspace/cards/{cardId}/&lt;key&gt;.md
        </span>
        : the members read and write it there; every save keeps a revision.
      </p>
      <div className="flex items-center gap-2">
        <Input
          aria-label="Document key"
          placeholder="launch-plan"
          pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,63}"
          value={value}
          onChange={(e) => {
            onChange(e.currentTarget.value);
          }}
          className="max-w-xs"
        />
        <Button
          type="submit"
          variant="primary"
          disabled={busy || !value.trim()}
        >
          {busy ? "Creating…" : "Create"}
        </Button>
        {onCancel && (
          <Button type="button" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
      <FormStatus error={error} />
    </form>
  );
}
