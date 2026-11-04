"use client";

import { useState, useTransition, type ReactNode } from "react";
import type { AgentMemory, WorkspaceIdentity } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { Textarea } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { Markdown } from "@/shared/ui/markdown";
import { saveIdentity, saveMemory } from "./identity-actions";

/**
 * Who the workspace's agent is (SOUL.md) and what it remembers. AGOS writes
 * SOUL.md; the fixed working rules are shown but can't be edited. Memory is
 * the agent's own (Hermes), kept per workspace, never shared.
 */
export function IdentitySettings({
  workspaceId,
  identity,
}: {
  workspaceId: string;
  identity: WorkspaceIdentity;
}) {
  return (
    <div className="flex max-w-3xl flex-col gap-10">
      {!identity.ready && (
        <p className="rounded-lg border border-dashed border-line px-3 py-2 text-sm text-ink-2">
          This workspace&apos;s agent isn&apos;t set up yet (is Docker
          running?). What you save here is written as soon as it is.
        </p>
      )}
      <IdentityEditor workspaceId={workspaceId} identity={identity} />
      <Section
        title="Working rules"
        description="Fixed by AGOS for every workspace. They always come after the identity above."
      >
        <div className="rounded-xl border border-line bg-sunken/50 px-4 py-3 text-sm text-ink-2">
          <Markdown text={identity.rules} className="text-sm" />
        </div>
      </Section>
      <MemoryEditor
        workspaceId={workspaceId}
        memory={identity.memory}
        title="What the agent remembers"
        description="Notes the agent keeps between sessions (facts, conventions, lessons). Only this workspace sees them."
        disabled={!identity.ready}
      />
      <MemoryEditor
        workspaceId={workspaceId}
        memory={identity.user}
        title="What the agent knows about you"
        description="Your preferences as the agent learned them in this workspace."
        disabled={!identity.ready}
      />
      <p className="text-xs text-ink-3">
        Changes apply from the agent&apos;s next session or task run. Deleting a
        chat never removes what the agent learned.
      </p>
    </div>
  );
}

function Section({
  title,
  description,
  action,
  children,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-display text-base font-semibold">{title}</h2>
          {description && (
            <p className="mt-1 text-sm text-ink-2">{description}</p>
          )}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function IdentityEditor({
  workspaceId,
  identity,
}: {
  workspaceId: string;
  identity: WorkspaceIdentity;
}) {
  const [text, setText] = useState(identity.identity);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  const custom = identity.identity.trim().length > 0;
  function save(value: string) {
    setSaved(false);
    setError(null);
    start(async () => {
      const result = await saveIdentity(workspaceId, value);
      if (result.error) setError(result.error);
      else setSaved(true);
    });
  }
  return (
    <Section
      title="Identity"
      description="Who the agent is and what this workspace is for. Leave it empty to use the name and description."
    >
      <Textarea
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setSaved(false);
        }}
        placeholder={identity.defaultIdentity}
        rows={6}
        aria-label="Identity"
      />
      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="primary"
          disabled={busy || text === identity.identity}
          onClick={() => {
            save(text);
          }}
        >
          Save identity
        </Button>
        {custom && (
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() => {
              setText("");
              save("");
            }}
          >
            Use name and description
          </Button>
        )}
        <span className="text-xs text-ink-3">
          {text.length.toLocaleString()} characters
        </span>
        <FormStatus
          error={error}
          saved={saved}
          savedText="Saved. Used from the next session."
        />
      </div>
    </Section>
  );
}

function MemoryEditor({
  workspaceId,
  memory,
  title,
  description,
  disabled,
}: {
  workspaceId: string;
  memory: AgentMemory;
  title: string;
  description: string;
  disabled: boolean;
}) {
  const [entries, setEntries] = useState<string[]>(memory.entries);
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  const used = entries.join("\n§\n").length;
  const over = used > memory.limit;

  function commit(next: string[]) {
    setError(null);
    const previous = entries;
    setEntries(next);
    start(async () => {
      const result = await saveMemory(workspaceId, memory.target, next);
      if (result.error) {
        setError(result.error);
        setEntries(previous);
      }
    });
  }

  return (
    <Section
      title={title}
      description={description}
      action={
        <span
          className={
            over
              ? "text-xs text-danger"
              : "text-xs whitespace-nowrap text-ink-3"
          }
        >
          {used.toLocaleString()} characters
        </span>
      }
    >
      {entries.length === 0 && editing !== -1 && (
        <p className="text-sm text-ink-3">Nothing yet.</p>
      )}
      <ul className="flex flex-col gap-2">
        {entries.map((entry, i) =>
          editing === i ? (
            <li key={i}>
              <EntryForm
                value={draft}
                onChange={setDraft}
                busy={busy}
                onCancel={() => {
                  setEditing(null);
                }}
                onSave={() => {
                  const next = [...entries];
                  next[i] = draft;
                  setEditing(null);
                  commit(next.filter((e) => e.trim()));
                }}
              />
            </li>
          ) : (
            <li
              key={i}
              className="group flex items-start gap-3 rounded-xl border border-line bg-panel px-3.5 py-2.5"
            >
              <p className="min-w-0 flex-1 text-sm whitespace-pre-wrap text-ink">
                {entry}
              </p>
              {!disabled && (
                <span className="flex shrink-0 gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                  <button
                    type="button"
                    className="rounded px-1.5 text-xs text-ink-2 hover:text-ink"
                    onClick={() => {
                      setDraft(entry);
                      setEditing(i);
                    }}
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    className="rounded px-1.5 text-xs text-danger hover:underline"
                    disabled={busy}
                    onClick={() => {
                      commit(entries.filter((_, j) => j !== i));
                    }}
                  >
                    Remove
                  </button>
                </span>
              )}
            </li>
          ),
        )}
        {editing === -1 && (
          <li>
            <EntryForm
              value={draft}
              onChange={setDraft}
              busy={busy}
              onCancel={() => {
                setEditing(null);
              }}
              onSave={() => {
                setEditing(null);
                if (draft.trim()) commit([...entries, draft]);
              }}
            />
          </li>
        )}
      </ul>
      {!disabled && editing === null && (
        <div>
          <Button
            onClick={() => {
              setDraft("");
              setEditing(-1);
            }}
          >
            Add a note
          </Button>
        </div>
      )}
      <FormStatus error={error} />
    </Section>
  );
}

function EntryForm({
  value,
  onChange,
  onSave,
  onCancel,
  busy,
}: {
  value: string;
  onChange: (v: string) => void;
  onSave: () => void;
  onCancel: () => void;
  busy: boolean;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-accent/50 bg-panel p-2.5">
      <Textarea
        autoFocus
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
        }}
        rows={3}
        aria-label="Note"
        className="border-0 focus-visible:border-0"
      />
      <div className="flex justify-end gap-2">
        <Button variant="ghost" className="h-8" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          variant="primary"
          className="h-8"
          disabled={busy || !value.trim()}
          onClick={onSave}
        >
          Save
        </Button>
      </div>
    </div>
  );
}
