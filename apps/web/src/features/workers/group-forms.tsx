"use client";

import { useState, useTransition } from "react";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { createGroup, setGroupMembers } from "./actions";
import { PANEL } from "@/shared/ui/panel";

type Member = { name: string; title: string };

function MemberChecks({
  members,
  picked,
  onChange,
}: {
  members: Member[];
  picked: string[];
  onChange: (next: string[]) => void;
}) {
  if (members.length === 0)
    return (
      <p className="text-sm text-ink-3">
        No members yet: turn agents on in this workspace&apos;s Capabilities.
      </p>
    );
  return (
    <ul className="flex flex-col gap-1">
      {members.map((m) => {
        const on = picked.includes(m.name);
        return (
          <li key={m.name}>
            <label className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm hover:bg-sunken">
              <input
                type="checkbox"
                checked={on}
                onChange={() => {
                  onChange(
                    on
                      ? picked.filter((p) => p !== m.name)
                      : [...picked, m.name],
                  );
                }}
                className="size-4 accent-accent"
              />
              <span className="text-ink">{m.title}</span>
              <span className="text-ink-3">@{m.name}</span>
            </label>
          </li>
        );
      })}
    </ul>
  );
}

/** "+" next to Groups: name + members. */
export function NewGroup({
  workspaceId,
  members,
}: {
  workspaceId: string;
  members: Member[];
}) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  return (
    <>
      <button
        type="button"
        aria-label="New group"
        title="New group"
        onClick={() => {
          setOpen(true);
        }}
        className="flex size-6 items-center justify-center rounded-md text-ink-3 hover:bg-panel hover:text-ink"
      >
        <svg
          viewBox="0 0 16 16"
          className="size-3.5"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.75}
          aria-hidden
        >
          <path d="M8 3.5v9M3.5 8h9" strokeLinecap="round" />
        </svg>
      </button>
      {open && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="New group"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={(e) => {
            if (e.target === e.currentTarget) setOpen(false);
          }}
        >
          <form
            className={`${PANEL} flex w-full max-w-sm flex-col gap-4 p-5 shadow-xl`}
            onSubmit={(e) => {
              e.preventDefault();
              setError(null);
              start(async () => {
                const result = await createGroup(workspaceId, title, picked);
                if (result.error) setError(result.error);
              });
            }}
          >
            <h2 className="font-display text-lg font-semibold">New group</h2>
            <input
              value={title}
              onChange={(e) => {
                setTitle(e.target.value);
              }}
              autoFocus
              placeholder="Name — e.g. Launch"
              aria-label="Group name"
              className="h-9 rounded-lg border border-line-strong bg-panel px-3 text-sm text-ink placeholder:text-ink-3 focus-visible:border-accent"
            />
            <div className="flex flex-col gap-1.5">
              <p className="text-sm font-medium text-ink">Members</p>
              <MemberChecks
                members={members}
                picked={picked}
                onChange={setPicked}
              />
              <p className="text-xs text-ink-3">
                The Co-Founder is always in the group.
              </p>
            </div>
            {error && (
              <p role="alert" className="text-sm text-danger">
                {error}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setOpen(false);
                }}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={busy || !title.trim()}>
                Create group
              </Button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}

/** Under a group's title: its members, editable. */
export function GroupMembers({
  workspaceId,
  chatId,
  current,
  members,
}: {
  workspaceId: string;
  chatId: number;
  current: string[];
  members: Member[];
}) {
  const [editing, setEditing] = useState(false);
  const [picked, setPicked] = useState(current);
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  const title = (name: string) =>
    members.find((m) => m.name === name)?.title ?? name;
  return (
    <div className="flex flex-wrap items-center gap-1.5 border-b border-line px-4 py-2 text-xs sm:px-6">
      <span className="rounded-full bg-accent-soft px-2 py-0.5 text-accent">
        Co-Founder
      </span>
      {current.map((name) => (
        <span
          key={name}
          className={cn(
            "rounded-full bg-sunken px-2 py-0.5",
            members.some((m) => m.name === name)
              ? "text-ink-2"
              : "text-ink-3 line-through",
          )}
          title={
            members.some((m) => m.name === name)
              ? undefined
              : "Turned off in Capabilities"
          }
        >
          @{name} · {title(name)}
        </span>
      ))}
      <button
        type="button"
        onClick={() => {
          setPicked(current);
          setEditing(!editing);
        }}
        className="ml-1 text-ink-3 hover:text-accent"
      >
        {editing ? "Close" : "Members"}
      </button>
      {editing && (
        <div className="flex w-full flex-col gap-2 pt-2">
          <MemberChecks
            members={members}
            picked={picked}
            onChange={setPicked}
          />
          {error && (
            <p role="alert" className="text-danger">
              {error}
            </p>
          )}
          <Button
            type="button"
            className="h-8 self-start"
            disabled={busy}
            onClick={() => {
              start(async () => {
                const result = await setGroupMembers(
                  workspaceId,
                  chatId,
                  picked,
                );
                if (result.error) setError(result.error);
                else setEditing(false);
              });
            }}
          >
            Save members
          </Button>
        </div>
      )}
    </div>
  );
}
