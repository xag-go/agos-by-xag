"use client";

import { useState, useTransition } from "react";
import { Button } from "@/shared/ui/button";
import { useAsk } from "@/shared/ui/confirm";
import {
  addMethod,
  addOwnerRule,
  deleteMethod,
  deleteOwnerRule,
  editMethod,
  editOwnerRule,
} from "./owner-rules-actions";
import { Panel } from "@/shared/ui/panel";

export interface OwnerRule {
  id: number;
  text: string;
  fromWorkspace?: string | null;
  createdAt: string;
}

type Kind = "rules" | "brain";

const TEXTS: Record<
  Kind,
  {
    placeholder: string;
    add: string;
    edit: string;
    label: string;
    remove: string;
    removeBody: string;
    empty: string;
  }
> = {
  rules: {
    placeholder: "e.g. Keep answers short. Reply in my language.",
    add: "Add rule",
    edit: "Edit rule",
    label: "Rule",
    remove: "Remove this rule?",
    removeBody: "Your workspaces stop following it from their next message.",
    empty: "No rule yet.",
  },
  brain: {
    placeholder: "e.g. Read the whole error before trying again.",
    add: "Add method",
    edit: "Edit method",
    label: "Method",
    remove: "Remove this method?",
    removeBody: "Your workspaces stop using it from their next message.",
    empty: "No method yet.",
  },
};

/** Rules about the owner (not a project) that every workspace's agents follow. */
export function OwnerRules({
  rules,
  workspaces,
  kind = "rules",
}: {
  rules: OwnerRule[];
  workspaces: { id: string; name: string }[];
  kind?: Kind;
}) {
  const t = TEXTS[kind];
  const doAdd = kind === "brain" ? addMethod : addOwnerRule;
  const doEdit = kind === "brain" ? editMethod : editOwnerRule;
  const doDelete = kind === "brain" ? deleteMethod : deleteOwnerRule;
  const [draft, setDraft] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const { dialog, ask, confirm } = useAsk();
  const nameOf = (id?: string | null) =>
    workspaces.find((w) => w.id === id)?.name ?? id ?? "";

  const run = (job: () => Promise<{ error?: string | null }>) =>
    start(async () => {
      const r = await job();
      setNote(r.error ?? null);
    });

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      {dialog}
      <Panel className="p-5">
        {kind === "brain" ? (
          <p className="text-sm text-ink-2">
            Ways of working the whole team learned, good for{" "}
            <strong className="text-ink">any</strong> project: how to check
            work, how to handle an error, how to plan. Every workspace&apos;s
            agents use them. A method never holds a project&apos;s names,
            topics, files or data, so nothing from one project leaks into
            another. A Co-Founder can propose one when a lesson worked more than
            once; it waits for your Approve. Each workspace can turn one off in
            Workspace settings → What I learned.
          </p>
        ) : (
          <p className="text-sm text-ink-2">
            Things about <strong className="text-ink">you</strong>, true in
            every project: your language, how you want to be asked, how you like
            reports. Every workspace&apos;s agents follow them. A project&apos;s
            own work (its topics, files, decisions) never goes here, so nothing
            from one project leaks into another. A Co-Founder can propose one
            when you say &ldquo;dima&rdquo; / &ldquo;f kolchi&rdquo;; it waits
            for your Approve.
          </p>
        )}
        <form
          className="mt-4 flex flex-col gap-2 sm:flex-row"
          onSubmit={(e) => {
            e.preventDefault();
            const text = draft.trim();
            if (!text) return;
            run(async () => {
              const r = await doAdd(text);
              if (!r.error) setDraft("");
              return r;
            });
          }}
        >
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={t.placeholder}
            className="h-10 flex-1 rounded-lg border border-line bg-paper px-3 text-sm"
          />
          <Button
            type="submit"
            variant="primary"
            disabled={pending || !draft.trim()}
          >
            {t.add}
          </Button>
        </form>
        {note && <p className="mt-2 text-sm text-danger">{note}</p>}
      </Panel>

      {rules.length === 0 ? (
        <p className="text-sm text-ink-3">{t.empty}</p>
      ) : (
        <ol className="flex flex-col gap-2">
          {rules.map((rule, i) => (
            <li
              key={rule.id}
              className="group flex items-start gap-3 rounded-xl border border-line bg-panel px-4 py-3"
            >
              <span className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-full bg-accent/15 text-xs font-semibold text-accent">
                {i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm whitespace-pre-wrap text-ink">
                  {rule.text}
                </p>
                <p className="mt-1 text-xs text-ink-3">
                  {rule.fromWorkspace
                    ? `Learned in ${nameOf(rule.fromWorkspace)}`
                    : "Added by you"}{" "}
                  · {rule.createdAt.slice(0, 10)}
                </p>
              </div>
              <div className="flex shrink-0 gap-1 opacity-70 group-hover:opacity-100">
                <Button
                  variant="ghost"
                  disabled={pending}
                  onClick={() =>
                    void (async () => {
                      const text = await ask({
                        title: t.edit,
                        confirmLabel: "Save",
                        input: { label: t.label, initial: rule.text },
                      });
                      if (text && text.trim() && text.trim() !== rule.text)
                        run(() => doEdit(rule.id, text.trim()));
                    })()
                  }
                >
                  Edit
                </Button>
                <Button
                  variant="ghost"
                  disabled={pending}
                  onClick={() =>
                    void (async () => {
                      if (
                        await confirm({
                          title: t.remove,
                          body: t.removeBody,
                          confirmLabel: "Remove",
                          danger: true,
                        })
                      )
                        run(() => doDelete(rule.id));
                    })()
                  }
                >
                  Remove
                </Button>
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
