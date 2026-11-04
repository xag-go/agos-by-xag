"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import type { AccessLists } from "@/data/queries";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { saveAccessLists, setWorkspaceAccess } from "./actions";

/** Saved the moment it is picked (no Save button), like the Autonomy table. */
export function AgentAccess({
  workspaceId,
  value,
  lists,
}: {
  workspaceId: string;
  value: "ask" | "full";
  lists: AccessLists;
}) {
  const [shown, setShown] = useState(value);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, start] = useTransition();
  const options = [
    {
      value: "ask",
      title: "Ask me first",
      hint: "Each place follows what you said there: a task that runs by itself runs its commands; one you asked to come back to you, an automation set to “Check with me first”, or a chat on “Ask me” waits for your Allow once / Deny.",
    },
    {
      value: "full",
      title: "Full access",
      hint: "Everything in this workspace runs commands without asking you, everywhere: tasks, automations, every chat. Only inside this workspace's sandbox; only catastrophic commands (like wiping the whole disk) stay blocked.",
    },
  ] as const;
  return (
    <section className="flex flex-col gap-4" aria-labelledby="access-title">
      <div>
        <h2 id="access-title" className="font-display text-base font-semibold">
          Agent access
        </h2>
        <p className="mt-1 text-sm text-ink-2">
          Risky commands, for everything in this workspace: tasks, task chats,
          automations and chats. The Autonomy table below then says, per member,
          what kind of work it may do on its own. This is Hermes&apos;s own
          approvals.mode, with its deny and allow rules below;{" "}
          <Link href="/settings/hermes?q=approvals" className="underline">
            Hermes&apos;s other approval settings
          </Link>{" "}
          are in Settings → Hermes settings.
        </p>
      </div>
      <div className="grid gap-2 sm:grid-cols-2" role="radiogroup">
        {options.map((o) => (
          <label
            key={o.value}
            className="flex cursor-pointer gap-3 rounded-xl border border-line bg-panel p-3.5 has-[:checked]:border-accent has-[:checked]:bg-accent-soft/40 has-[:disabled]:cursor-wait"
          >
            <input
              type="radio"
              name="chatAccess"
              value={o.value}
              checked={shown === o.value}
              disabled={busy}
              onChange={() => {
                const before = shown;
                setShown(o.value);
                setSaved(false);
                start(async () => {
                  const r = await setWorkspaceAccess(workspaceId, o.value);
                  setError(r.error);
                  if (r.error) setShown(before);
                  else setSaved(true);
                });
              }}
              className="mt-1 accent-accent"
            />
            <span className="flex flex-col gap-0.5">
              <span className="text-sm font-medium text-ink">{o.title}</span>
              <span className="text-xs text-ink-2">{o.hint}</span>
            </span>
          </label>
        ))}
      </div>
      <FormStatus error={error} saved={saved} savedText="Saved." />
      <CommandRules workspaceId={workspaceId} lists={lists} />
    </section>
  );
}

/** Hermes's own deny and allow rules for commands (approvals.deny,
 * command_allowlist), the floor Full access relies on. */
function CommandRules({
  workspaceId,
  lists,
}: {
  workspaceId: string;
  lists: AccessLists;
}) {
  const savedDeny = lists.deny ?? [];
  const savedAllow = lists.allow ?? [];
  const [deny, setDeny] = useState(savedDeny);
  const [allow, setAllow] = useState(savedAllow);
  const [status, setStatus] = useState<{
    error: string | null;
    saved?: boolean;
  }>({ error: null });
  const [busy, start] = useTransition();
  const changed =
    JSON.stringify(deny) !== JSON.stringify(savedDeny) ||
    JSON.stringify(allow) !== JSON.stringify(savedAllow);
  return (
    <div className="flex flex-col gap-4 rounded-xl border border-line bg-panel p-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <RuleList
          title="Never run (deny rules)"
          hint="Hermes blocks a command matching one of these, even with Full access. Patterns like git push --force* (case-insensitive). Hermes's approvals.deny."
          placeholder="e.g. git push --force*"
          entries={deny}
          onChange={setDeny}
        />
        <RuleList
          title="Run without asking (allow rules)"
          hint="Commands (or patterns like npm test*) Hermes runs without asking under Ask me first. Hermes also adds here when you answer “Always allow”. Hermes's command_allowlist."
          placeholder="e.g. npm test*"
          entries={allow}
          onChange={setAllow}
        />
      </div>
      <p className="text-xs text-ink-3">
        Saved into this workspace&apos;s Co-Founder and each member (a member
        keeps the entries only it has, like its own “Always allow”).
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="primary"
          disabled={busy || !changed}
          onClick={() => {
            start(async () => {
              setStatus(await saveAccessLists(workspaceId, { deny, allow }));
            });
          }}
        >
          {busy ? "Saving…" : "Save rules"}
        </Button>
        <FormStatus
          error={status.error}
          saved={status.saved}
          savedText="Rules saved."
        />
      </div>
    </div>
  );
}

function RuleList({
  title,
  hint,
  placeholder,
  entries,
  onChange,
}: {
  title: string;
  hint: string;
  placeholder: string;
  entries: string[];
  onChange: (next: string[]) => void;
}) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const text = draft.trim();
    if (!text) return;
    if (!entries.includes(text)) onChange([...entries, text]);
    setDraft("");
  };
  return (
    <div className="flex flex-col gap-2">
      <span className="text-sm font-medium text-ink">{title}</span>
      <span className="text-xs text-ink-2">{hint}</span>
      {entries.length === 0 ? (
        <span className="text-xs text-ink-3">None.</span>
      ) : (
        <ul className="flex flex-col gap-1">
          {entries.map((e) => (
            <li
              key={e}
              className="flex items-center justify-between gap-2 rounded-lg bg-sunken px-2.5 py-1"
            >
              <code className="text-xs break-all">{e}</code>
              <button
                type="button"
                className="text-xs text-ink-2 underline"
                aria-label={`Remove ${e}`}
                onClick={() => {
                  onChange(entries.filter((x) => x !== e));
                }}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex gap-2">
        <Input
          value={draft}
          placeholder={placeholder}
          aria-label={`Add to ${title}`}
          onChange={(ev) => {
            setDraft(ev.target.value);
          }}
          onKeyDown={(ev) => {
            if (ev.key === "Enter") {
              ev.preventDefault();
              add();
            }
          }}
        />
        <Button type="button" onClick={add} disabled={!draft.trim()}>
          Add
        </Button>
      </div>
    </div>
  );
}
