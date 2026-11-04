"use client";

import { useState, useTransition } from "react";
import { Button } from "@/shared/ui/button";
import { Field, Input, Select } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { Markdown } from "@/shared/ui/markdown";
import { cn } from "@/shared/ui/cn";
import { saveTrustedApps, setAutonomy, undoLearned } from "./actions";

export type LearnedChange = {
  id: string;
  at: string;
  by: string;
  action: string;
  skill: string;
  source: { label: string; href: string } | null;
  before: string | null;
  after: string | null;
  undone: boolean;
};

export type Learned = {
  changes: LearnedChange[];
  memory: string;
  user: string;
  // Each member's own notes (its own Hermes profile), when it has any.
  memories?: { agent: string; memory: string; user: string }[];
  feedback: {
    at: string;
    kind: string;
    subject: string;
    detail: string;
    agent: string | null;
    learned: boolean;
  }[];
};

export type AutonomyView = {
  actions: { key: string; label: string; hint: string; default: string }[];
  agents: { id: string; title: string }[];
  rules: Record<string, Record<string, string>>;
  trustedApps?: string[];
};

const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString() : "—";

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-4">
      <div>
        <h2 className="font-display text-base font-semibold">{title}</h2>
        {description && (
          <p className="mt-1 max-w-2xl text-sm text-ink-2">{description}</p>
        )}
      </div>
      {children}
    </section>
  );
}

/** Looking ahead: Check simple on its schedule + Check general when he asks. */
export function LearnedList({
  workspaceId,
  learned,
}: {
  workspaceId: string;
  learned: Learned;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  return (
    <div className="flex flex-col gap-10">
      <Section
        title="What I learned"
        description="After chats, tasks and automations the team reviews what happened and improves its own skills and notes, by itself. Every change is kept with the text before and after, so you can undo any of them."
      >
        {learned.changes.length === 0 ? (
          <p className="text-sm text-ink-3">Nothing learned yet.</p>
        ) : (
          <ul className="flex flex-col divide-y divide-line rounded-xl border border-line">
            {learned.changes.map((c) => (
              <li key={c.id} className="flex flex-col gap-2 px-4 py-3">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                  <span className="font-medium">
                    {c.action === "create"
                      ? "New skill"
                      : c.action === "delete"
                        ? "Removed skill"
                        : "Improved skill"}{" "}
                    “{c.skill}”
                  </span>
                  <span className="text-ink-3">
                    {when(c.at)} · {c.by}
                  </span>
                  {c.source && (
                    <a
                      href={c.source.href}
                      className="text-ink-2 underline-offset-2 hover:underline"
                    >
                      from {c.source.label}
                    </a>
                  )}
                  <span className="ml-auto flex gap-2">
                    {(c.before ?? c.after) !== null && (
                      <Button
                        variant="ghost"
                        onClick={() => {
                          setOpen(open === c.id ? null : c.id);
                        }}
                      >
                        {open === c.id ? "Hide" : "See the change"}
                      </Button>
                    )}
                    {!c.undone && (
                      <Button
                        variant="ghost"
                        disabled={busy}
                        onClick={() => {
                          setError(null);
                          start(async () => {
                            const r = await undoLearned(workspaceId, c.id);
                            if (r.error) setError(r.error);
                          });
                        }}
                      >
                        Undo
                      </Button>
                    )}
                  </span>
                </div>
                {open === c.id && (
                  <div className="grid gap-3 md:grid-cols-2">
                    <pre className="max-h-96 overflow-auto rounded-lg bg-sunken p-3 text-xs whitespace-pre-wrap">
                      {c.before ?? "(new)"}
                    </pre>
                    <pre className="max-h-96 overflow-auto rounded-lg bg-sunken p-3 text-xs whitespace-pre-wrap">
                      {c.after ?? "(removed)"}
                    </pre>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
        <FormStatus error={error} />
      </Section>
      <Section
        title="What it remembers"
        description="Its notes (it reads them in every session). Edit them in Identity & memory."
      >
        <div className="rounded-xl border border-line bg-sunken/50 px-4 py-3 text-sm">
          {learned.memory.trim() ? (
            <Markdown text={learned.memory.replaceAll("§", "\n\n")} />
          ) : (
            <span className="text-ink-3">Empty.</span>
          )}
        </div>
        {(learned.memories ?? []).map((m) => (
          <div
            key={m.agent}
            className="mt-2 rounded-xl border border-line bg-sunken/50 px-4 py-3 text-sm"
          >
            <p className="mb-1 font-medium">{m.agent}</p>
            {m.memory.trim() ? (
              <Markdown text={m.memory.replaceAll("§", "\n\n")} />
            ) : (
              <span className="text-ink-3">Empty.</span>
            )}
          </div>
        ))}
      </Section>
      <Section
        title="What you taught it"
        description="Your choices (approve, changes asked, cancel, dismiss, undo) become lessons the team follows from the next job on. The newest wins."
      >
        {learned.feedback.length === 0 ? (
          <p className="text-sm text-ink-3">Nothing yet.</p>
        ) : (
          <ul className="flex flex-col gap-1 text-sm">
            {learned.feedback.map((f, i) => (
              <li key={i} className="text-ink-2">
                <span className="text-ink-3">{when(f.at)}</span> · You {f.kind}{" "}
                {f.subject}
                {f.detail && <> — “{f.detail}”</>}
                {f.agent && <span className="text-ink-3"> ({f.agent})</span>}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

const CHOICES = [
  { value: "do", label: "Do it" },
  { value: "ask", label: "Ask me" },
  { value: "never", label: "Never" },
] as const;

/** Per agent: what it may do alone (Do it), with your OK (Ask me), or never. */
export function AutonomyTable({
  workspaceId,
  view,
}: {
  workspaceId: string;
  view: AutonomyView;
}) {
  const [agent, setAgent] = useState("*");
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  const base = view.rules["*"] ?? {};
  const own = view.rules[agent] ?? {};
  return (
    <Section
      title="Autonomy"
      description="What each member may do on its own. Ask me = it prepares the work and waits for your Approve (in the app and on your phone), even when the workspace is on Full access. Never = blocked before it runs. Passwords, logins, security settings and other workspaces are always off-limits."
    >
      <Field label="For">
        <Select
          value={agent}
          onChange={(e) => {
            setAgent(e.target.value);
          }}
          className="max-w-xs"
        >
          {view.agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.title}
            </option>
          ))}
        </Select>
      </Field>
      <ul className="flex flex-col divide-y divide-line rounded-xl border border-line">
        {view.actions.map((a) => {
          const value = agent === "*" ? (base[a.key] ?? a.default) : own[a.key];
          const inherited = agent !== "*" && !own[a.key];
          const shown = value ?? base[a.key] ?? a.default;
          return (
            <li
              key={a.key}
              className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
            >
              <div>
                <div className="text-sm font-medium">{a.label}</div>
                <div className="text-xs text-ink-3">
                  {a.hint}
                  {inherited && " · same as everyone"}
                </div>
              </div>
              <div
                className="flex overflow-hidden rounded-lg border border-line"
                role="radiogroup"
                aria-label={a.label}
              >
                {CHOICES.map((c) => (
                  <button
                    key={c.value}
                    type="button"
                    role="radio"
                    aria-checked={shown === c.value}
                    disabled={busy}
                    className={cn(
                      "px-3 py-1.5 text-sm",
                      shown === c.value
                        ? c.value === "never"
                          ? "bg-danger text-accent-ink"
                          : "bg-accent text-accent-ink"
                        : "text-ink-2 hover:bg-sunken",
                    )}
                    onClick={() => {
                      setError(null);
                      start(async () => {
                        const r = await setAutonomy(
                          workspaceId,
                          agent,
                          a.key,
                          c.value,
                        );
                        if (r.error) setError(r.error);
                      });
                    }}
                  >
                    {c.label}
                  </button>
                ))}
              </div>
            </li>
          );
        })}
      </ul>
      <FormStatus error={error} />
      <TrustedApps workspaceId={workspaceId} apps={view.trustedApps ?? []} />
    </Section>
  );
}

/** Apps whose answers don't make a member ask you first (read vs act). */
function TrustedApps({
  workspaceId,
  apps,
}: {
  workspaceId: string;
  apps: string[];
}) {
  const [text, setText] = useState(apps.join(", "));
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, start] = useTransition();
  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        setError(null);
        setSaved(false);
        start(async () => {
          const names = text
            .split(/[\s,]+/)
            .map((n) => n.trim())
            .filter(Boolean);
          const r = await saveTrustedApps(workspaceId, names);
          if (r.error) setError(r.error);
          else setSaved(true);
        });
      }}
    >
      <Field
        label="Trusted apps"
        hint="After a member reads a web page, an email or an app's answer, it asks you before it changes what agents can do. Apps listed here (your own, e.g. linear, notion) don't count as outside. Empty = every app counts as outside."
      >
        <Input
          value={text}
          onChange={(e) => {
            setText(e.target.value);
          }}
          placeholder="none"
          className="max-w-md"
        />
      </Field>
      <div>
        <Button type="submit" disabled={busy}>
          Save
        </Button>
      </div>
      <FormStatus error={error} saved={saved} />
    </form>
  );
}
