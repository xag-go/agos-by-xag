"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import type { DocFinding, DocOpen, DocsIndex } from "@/data/queries";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { useAsk } from "@/shared/ui/confirm";
import { Input, Textarea } from "@/shared/ui/field";
import { Markdown } from "@/shared/ui/markdown";
import {
  deleteDoc,
  newDoc,
  restoreAgent,
  restoreVersion,
  saveDoc,
  setLatinOnly,
  versionDiff,
} from "./actions";
import { Panel } from "@/shared/ui/panel";

const FINDING: Record<DocFinding["kind"], string> = {
  duplicate: "Written twice",
  pointer: "Broken pointer",
  orphan: "Nobody reads it",
  language: "Language",
};

/** The team's rules: one home per rule, read by the agents on every job. */
export function DocsView({
  workspaceId,
  index,
  open,
}: {
  workspaceId: string;
  index: DocsIndex;
  open: DocOpen | null;
}) {
  const base = `/w/${workspaceId}/docs`;
  const { dialog, ask, confirm } = useAsk();
  const router = useRouter();
  const [busy, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const rules = index.files.filter((f) => !f.path.includes("/"));
  const others = index.files.filter((f) => f.path.includes("/"));

  return (
    <div className="flex flex-col gap-6" data-fill>
      {dialog}
      <Explainer />
      <div className="grid min-h-0 flex-1 gap-6 lg:grid-cols-[18rem_1fr]">
        <aside className="flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-ink-2">Rule files</h2>
            <button
              type="button"
              disabled={busy}
              className="text-sm text-accent hover:underline"
              onClick={() => {
                void (async () => {
                  const path = await ask({
                    title: "New rule file",
                    body: "One subject per file, e.g. publishing.md. Add it to README.md after.",
                    input: { label: "File name" },
                    confirmLabel: "Create",
                  });
                  if (!path) return;
                  start(async () => {
                    const r = await newDoc(workspaceId, path, "new rule file");
                    if (r.error) setError(r.error);
                    else
                      router.push(
                        `${base}?f=${encodeURIComponent(path.endsWith(".md") ? path : `${path}.md`)}`,
                      );
                  });
                })();
              }}
            >
              + New
            </button>
          </div>
          <FileList base={base} files={rules} current={open?.path} />
          {others.length > 0 && (
            <details className="text-sm">
              <summary className="cursor-pointer text-ink-3">
                Other files ({others.length})
              </summary>
              <FileList base={base} files={others} current={open?.path} />
            </details>
          )}
          <Checks findings={index.findings} base={base} />
          <label className="flex items-center gap-2 text-sm text-ink-2">
            <input
              type="checkbox"
              checked={index.latinOnly}
              disabled={busy}
              onChange={(e) => {
                const on = e.target.checked;
                start(async () => {
                  const r = await setLatinOnly(workspaceId, on);
                  if (r.error) setError(r.error);
                });
              }}
            />
            Latin letters only (no Arabic script) in rules and agents
          </label>
          {index.deletedAgents.length > 0 && (
            <div className="flex flex-col gap-2 rounded-2xl border border-line p-3">
              <p className="text-sm font-medium">Deleted agents</p>
              <p className="text-xs text-ink-3">
                Bring one back with the same ID, text and rules it read.
              </p>
              {index.deletedAgents.map((a) => (
                <div
                  key={a.id}
                  className="flex items-center justify-between gap-2 text-sm"
                >
                  <span className="truncate">{a.title}</span>
                  <button
                    type="button"
                    className="text-accent hover:underline"
                    disabled={busy}
                    onClick={() => {
                      start(async () => {
                        const r = await restoreAgent(workspaceId, a.id);
                        if (r.error) setError(r.error);
                      });
                    }}
                  >
                    Bring back
                  </button>
                </div>
              ))}
            </div>
          )}
          {error && <p className="text-sm text-danger">{error}</p>}
        </aside>
        <section className="min-w-0">
          {open ? (
            <Editor
              key={`${open.path}:${open.hash}`}
              workspaceId={workspaceId}
              doc={open}
              onDelete={async () => {
                const why = await ask({
                  title: `Delete ${open.path}?`,
                  body: "Its text stays in the history. Agents that read it stop getting it.",
                  input: { label: "Why" },
                  confirmLabel: "Delete",
                  danger: true,
                });
                if (why === null) return;
                start(async () => {
                  const r = await deleteDoc(workspaceId, open.path, why);
                  if (r.error) setError(r.error);
                  else router.push(base);
                });
              }}
              confirm={confirm}
            />
          ) : (
            <p className="text-sm text-ink-3">Pick a file.</p>
          )}
        </section>
      </div>
    </div>
  );
}

function Explainer() {
  const rows = [
    [
      "Agent",
      "The employee",
      "Who it is, what it does and doesn't, its steps in short, its skills, tools and rights, which rules it reads, who it hands work to, how it reports.",
    ],
    [
      "Skill",
      "The know-how",
      "How one job is done, in full: steps, templates, examples, quality checks.",
    ],
    [
      "Documentation",
      "The rulebook",
      "Your facts and decisions: what each status means, who sets done, where the Sheets and Drive are, who each style is, the language. Short: agents read it on every job.",
    ],
  ];
  return (
    <Panel as="details" className="px-4 py-3 text-sm">
      <summary className="cursor-pointer font-medium">
        Where does a rule go? Agent, skill or documentation
      </summary>
      <table className="mt-3 w-full text-left">
        <tbody>
          {rows.map(([kind, role, what]) => (
            <tr key={kind} className="border-t border-line align-top">
              <td className="py-2 pr-4 font-medium">{kind}</td>
              <td className="py-2 pr-4 whitespace-nowrap text-ink-2">{role}</td>
              <td className="py-2 text-ink-2">{what}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-ink-3">
        “How is it done?” → skill. “What is our rule or decision?” →
        documentation. “Who does it, with what?” → agent.
      </p>
    </Panel>
  );
}

function FileList({
  base,
  files,
  current,
}: {
  base: string;
  files: DocsIndex["files"];
  current?: string;
}) {
  return (
    <ul className="flex flex-col gap-0.5">
      {files.map((f) => (
        <li key={f.path}>
          <Link
            href={`${base}?f=${encodeURIComponent(f.path)}`}
            scroll={false}
            className={cn(
              "flex items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-sm",
              current === f.path
                ? "bg-sunken font-medium text-ink"
                : "text-ink-2 hover:bg-sunken hover:text-ink",
            )}
          >
            <span className="truncate font-mono text-body-sm">{f.path}</span>
            {f.rule && (
              <span
                className={cn(
                  "shrink-0 text-xs",
                  f.readBy.length ? "text-ink-3" : "text-attention",
                )}
                title={
                  f.readBy.length
                    ? `Read by ${f.readBy.map((r) => r.title).join(", ")}`
                    : "No agent reads it"
                }
              >
                {f.readBy.length ? `${String(f.readBy.length)} read` : "unread"}
              </span>
            )}
          </Link>
        </li>
      ))}
    </ul>
  );
}

function Checks({ findings, base }: { findings: DocFinding[]; base: string }) {
  if (findings.length === 0)
    return (
      <p className="rounded-2xl border border-line px-3 py-2 text-sm text-live">
        ✓ Checks pass: no rule written twice, no broken pointer.
      </p>
    );
  return (
    <details className="rounded-2xl border border-attention/40 bg-attention/5 px-3 py-2 text-sm">
      <summary className="cursor-pointer font-medium text-attention">
        {findings.length} to look at
      </summary>
      <ul className="mt-2 flex flex-col gap-2">
        {findings.slice(0, 60).map((f, i) => (
          <li key={i} className="flex flex-col">
            <span className="text-xs font-medium text-ink-2">
              {FINDING[f.kind]} ·{" "}
              {f.where.endsWith(".md") ? (
                <Link
                  className="underline"
                  href={`${base}?f=${encodeURIComponent(f.where)}`}
                >
                  {f.where}
                </Link>
              ) : (
                f.where
              )}
              {f.other ? ` & ${f.other}` : ""}
            </span>
            <span className="text-ink-2">{f.detail}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}

function Editor({
  workspaceId,
  doc,
  onDelete,
  confirm,
}: {
  workspaceId: string;
  doc: DocOpen;
  onDelete: () => Promise<void>;
  confirm: (q: {
    title: string;
    body?: string;
    confirmLabel?: string;
  }) => Promise<boolean>;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(doc.text);
  const [why, setWhy] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [findings, setFindings] = useState<DocFinding[] | null>(null);
  const [diff, setDiff] = useState<{ id: number; diff: string } | null>(null);
  const [busy, start] = useTransition();
  const locked = doc.path === "CHANGES.md";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-mono text-lg">{doc.path}</h2>
          <p className="text-sm text-ink-3">
            {doc.readBy.length
              ? `Read by ${doc.readBy
                  .map(
                    (r) =>
                      `${r.title}${r.mode === "demand" ? " (when needed)" : ""}`,
                  )
                  .join(", ")}`
              : locked
                ? "The log of every rule change, written by AGOS."
                : "No agent reads this file yet (set it in the agent's “Reads”)."}
          </p>
        </div>
        {!locked && !editing && (
          <div className="flex gap-2">
            <Button
              onClick={() => {
                setEditing(true);
              }}
            >
              Edit
            </Button>
            {doc.path !== "README.md" && (
              <Button
                onClick={() => {
                  void onDelete();
                }}
              >
                Delete
              </Button>
            )}
          </div>
        )}
      </div>

      {editing ? (
        <div className="flex flex-col gap-3">
          <Textarea
            rows={24}
            className="font-mono text-body-sm leading-relaxed"
            value={text}
            onChange={(e) => {
              setText(e.target.value);
            }}
          />
          <Input
            placeholder="Why this change? (goes in CHANGES.md)"
            value={why}
            onChange={(e) => {
              setWhy(e.target.value);
            }}
          />
          {error && <p className="text-sm text-danger">{error}</p>}
          <div className="flex gap-2">
            <Button
              variant="primary"
              disabled={busy || !why.trim() || text === doc.text}
              onClick={() => {
                start(async () => {
                  const r = await saveDoc(
                    workspaceId,
                    doc.path,
                    text,
                    why,
                    doc.hash,
                  );
                  if (r.error) setError(r.error);
                  else {
                    setFindings(r.findings ?? []);
                    setEditing(false);
                  }
                });
              }}
            >
              Save
            </Button>
            <Button
              disabled={busy}
              onClick={() => {
                setEditing(false);
                setText(doc.text);
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <Panel className="px-5 py-4">
          <Markdown text={doc.text} className="text-body leading-relaxed" />
        </Panel>
      )}

      {findings && findings.length > 0 && (
        <div className="rounded-2xl border border-attention/40 bg-attention/5 px-4 py-3 text-sm">
          <p className="font-medium text-attention">
            Saved. The checks found {findings.length} thing(s) to look at:
          </p>
          <ul className="mt-1 list-disc pl-5 text-ink-2">
            {findings.slice(0, 10).map((f, i) => (
              <li key={i}>
                {f.where}: {f.detail}
              </li>
            ))}
          </ul>
        </div>
      )}

      {doc.versions.length > 0 && (
        <details className="rounded-2xl border border-line px-4 py-3 text-sm">
          <summary className="cursor-pointer font-medium">
            History ({doc.versions.length})
          </summary>
          <ul className="mt-2 flex flex-col divide-y divide-line">
            {doc.versions.map((v, i) => (
              <li key={v.id} className="flex flex-col gap-1 py-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span>
                    <span className="text-ink-3">
                      {v.at.slice(0, 16).replace("T", " ")}
                    </span>{" "}
                    · {v.author} · {v.why || "—"}
                  </span>
                  <span className="flex gap-3">
                    <button
                      type="button"
                      className="text-accent hover:underline"
                      onClick={() => {
                        start(async () => {
                          const r = await versionDiff(workspaceId, v.id);
                          if (r) setDiff({ id: v.id, diff: r.diff });
                        });
                      }}
                    >
                      What changed
                    </button>
                    {i > 0 && !locked && (
                      <button
                        type="button"
                        className="text-accent hover:underline"
                        disabled={busy}
                        onClick={() => {
                          void (async () => {
                            const ok = await confirm({
                              title: "Go back to this version?",
                              body: "The current text stays in the history.",
                              confirmLabel: "Restore",
                            });
                            if (!ok) return;
                            start(async () => {
                              const r = await restoreVersion(workspaceId, v.id);
                              if (r.error) setError(r.error);
                            });
                          })();
                        }}
                      >
                        Restore
                      </button>
                    )}
                  </span>
                </div>
                {diff?.id === v.id && (
                  <pre className="max-h-80 overflow-auto rounded-lg bg-sunken p-3 font-mono text-xs leading-relaxed">
                    {diff.diff.split("\n").map((line, j) => (
                      <span
                        key={j}
                        className={cn(
                          "block",
                          line.startsWith("+") && !line.startsWith("+++")
                            ? "text-live"
                            : line.startsWith("-") && !line.startsWith("---")
                              ? "text-danger"
                              : "text-ink-3",
                        )}
                      >
                        {line || " "}
                      </span>
                    ))}
                  </pre>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
