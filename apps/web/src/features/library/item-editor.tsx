"use client";

import type { ModelSelection } from "@agos/core";
import { useState, useTransition } from "react";
import type {
  CatalogProvider,
  LibraryItem,
  LibraryKind,
  McpTest,
} from "@/data/types";
import { ModelPicker } from "@/features/models/model-picker";
import { firstChoice } from "@/features/models/first-choice";
import { KitEditor } from "@/features/workers/kit-editor";
import { sentKit, type Kit } from "@/features/workers/kit-types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { PANEL } from "@/shared/ui/panel";
import { Field, Input, Select, Textarea } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { saveLibraryItem, testMcp, type ItemDraft } from "./actions";
import {
  NOUN,
  SKILL_TEMPLATE,
  type DocChoice,
  type Read,
} from "./library-shared";

export function ItemEditor({
  kind,
  item,
  catalog,
  onDone,
  workspaceId,
  docFiles = [],
  teammates = [],
  frameless = false,
}: {
  kind: LibraryKind;
  item: LibraryItem | null;
  catalog: CatalogProvider[];
  onDone: () => void;
  /** An agent, skill or MCP server of this workspace (saved there, nowhere else). */
  workspaceId?: string;
  /** The workspace's rule files, to pick what the agent reads on every job. */
  docFiles?: DocChoice[];
  /** The team's other members, for "Reports to" (the org chart). */
  teammates?: { name: string; title: string }[];
  /** Inside a modal: the dialog is the frame, so none of its own. */
  frameless?: boolean;
}) {
  const def = (item?.definition ?? {}) as Record<string, unknown>;
  const [name, setName] = useState(item?.name ?? "");
  const [title, setTitle] = useState(item?.title ?? "");
  const [summary, setSummary] = useState(item?.summary ?? "");
  const [text, setText] = useState(
    typeof def.text === "string" ? def.text : SKILL_TEMPLATE,
  );
  const [url, setUrl] = useState(typeof def.url === "string" ? def.url : "");
  const [local, setLocal] = useState(
    def.transport === "command" || def.transport === "stdio",
  );
  const [command, setCommand] = useState(
    typeof def.command === "string" ? def.command : "",
  );
  const [envKey, setEnvKey] = useState(
    typeof def.env_key === "string" ? def.env_key : "",
  );
  const [authHeader, setAuthHeader] = useState(
    typeof def.auth_header === "string" ? def.auth_header : "",
  );
  const [authScheme, setAuthScheme] = useState(
    typeof def.auth_scheme === "string" ? def.auth_scheme : "Bearer",
  );
  const [instructions, setInstructions] = useState(
    typeof def.instructions === "string" ? def.instructions : "",
  );
  const [reads, setReads] = useState<Read[]>(
    Array.isArray(def.reads) ? (def.reads as Read[]) : [],
  );
  const [reportsTo, setReportsTo] = useState(
    typeof def.reports_to === "string" ? def.reports_to : "",
  );
  const [model, setModel] = useState<ModelSelection | null>(
    (def.model as ModelSelection | null | undefined) ?? null,
  );
  const [plugin, setPlugin] = useState(
    typeof def.plugin === "string" ? def.plugin : "",
  );
  // A new member of a workspace is a hire: its whole kit and its model are asked
  // for (the core refuses it without them, the same rules as every hire).
  const hiring = kind === "agent" && item === null && Boolean(workspaceId);
  const [kit, setKit] = useState<Kit>({
    tools: [{ name: "" }],
    skills: [{ name: "", source: "library" }],
    docs: [{ title: "", path: "" }],
    onboarding: { task: "", criteria: [""] },
  });
  const [error, setError] = useState<string | null>(null);
  const [test, setTest] = useState<McpTest | null>(null);
  const [busy, start] = useTransition();

  function draft(): ItemDraft {
    const definition: Record<string, unknown> =
      kind === "skill"
        ? { text }
        : kind === "mcp"
          ? local
            ? { transport: "command", command, env_key: envKey }
            : {
                transport: "http",
                url,
                auth_header: authHeader,
                auth_scheme: authHeader ? authScheme : "",
              }
          : kind === "agent"
            ? {
                ...def,
                instructions,
                model,
                reads,
                reports_to: reportsTo,
                ...(hiring ? { kit: sentKit(kit) } : {}),
              }
            : { plugin: plugin || name };
    const skillName =
      kind === "skill" ? (/^name:\s*(.+)$/m.exec(text)?.[1] ?? "").trim() : "";
    return {
      name: kind === "skill" ? skillName : name,
      title: title || (kind === "skill" ? skillName : name),
      summary,
      definition,
    };
  }

  return (
    <div className={cn("flex flex-col gap-4 p-5", frameless ? "p-6" : PANEL)}>
      <h3
        className={cn(
          "font-display font-semibold",
          frameless ? "text-lg" : "text-base",
        )}
      >
        {item ? `Edit ${item.title}` : `New ${NOUN[kind]}`}
      </h3>
      {kind !== "skill" && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="ID"
            hint="Lowercase letters, digits, dashes. Fixed once created; the name next to it can change any time."
          >
            <Input
              value={name}
              disabled={item !== null}
              onChange={(e) => {
                setName(e.target.value);
              }}
              maxLength={63}
            />
          </Field>
          <Field
            label="Name"
            hint={
              kind === "agent"
                ? "A real job title: what it does + the role, e.g. Ideas Generator, Script Writer."
                : undefined
            }
          >
            <Input
              value={title}
              placeholder={
                kind === "agent"
                  ? "Ideas Generator"
                  : name
                    ? name
                        .split(/[-_]+/)
                        .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
                        .join(" ")
                    : undefined
              }
              onChange={(e) => {
                setTitle(e.target.value);
              }}
            />
          </Field>
        </div>
      )}
      {kind === "skill" && (
        <Field
          label="SKILL.md"
          hint="Frontmatter with name and description, then the method. The Co-Founder and every agent of this workspace read this one copy."
        >
          <Textarea
            rows={14}
            value={text}
            onChange={(e) => {
              setText(e.target.value);
            }}
            className="font-mono text-xs"
          />
        </Field>
      )}
      {kind === "mcp" && (
        <Field label="Where it runs">
          <Select
            value={local ? "command" : "http"}
            onChange={(e) => {
              setLocal(e.target.value === "command");
            }}
          >
            <option value="http">Remote server (a URL)</option>
            <option value="command">
              Local server (a command, run in each workspace&apos;s own
              container)
            </option>
          </Select>
        </Field>
      )}
      {kind === "mcp" && local && (
        <>
          <Field
            label="Command"
            hint="What starts the server, e.g. npx -y @modelcontextprotocol/server-filesystem /workspace. It runs inside the workspace's container with only its files (/workspace) and the public internet, never on your machine."
          >
            <Input
              value={command}
              placeholder="npx -y @modelcontextprotocol/server-filesystem /workspace"
              onChange={(e) => {
                setCommand(e.target.value);
              }}
              className="font-mono text-xs"
            />
          </Field>
          <Field
            label="Key variable (optional)"
            hint="If the server reads its key from a variable (e.g. GITHUB_TOKEN). Each workspace enters its own key; it stays in that workspace's container."
          >
            <Input
              value={envKey}
              placeholder="GITHUB_TOKEN"
              onChange={(e) => {
                setEnvKey(e.target.value.toUpperCase());
              }}
            />
          </Field>
          <Field label="What it's for">
            <Input
              value={summary}
              onChange={(e) => {
                setSummary(e.target.value);
              }}
            />
          </Field>
        </>
      )}
      {kind === "mcp" && !local && (
        <>
          <Field label="Server URL" hint="A remote MCP server (https://…).">
            <Input
              value={url}
              placeholder="https://example.com/mcp"
              onChange={(e) => {
                setUrl(e.target.value);
              }}
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Credential header (optional)"
              hint="Each workspace enters its own credential."
            >
              <Input
                value={authHeader}
                placeholder="Authorization"
                onChange={(e) => {
                  setAuthHeader(e.target.value);
                }}
              />
            </Field>
            <Field label="Prefix">
              <Select
                value={authScheme}
                onChange={(e) => {
                  setAuthScheme(e.target.value);
                }}
              >
                <option value="Bearer">Bearer</option>
                <option value="">None</option>
                <option value="Token">Token</option>
              </Select>
            </Field>
          </div>
          <Field label="What it's for">
            <Input
              value={summary}
              onChange={(e) => {
                setSummary(e.target.value);
              }}
            />
          </Field>
        </>
      )}
      {kind === "agent" && (
        <>
          <Field label="What it's for">
            <Input
              value={summary}
              onChange={(e) => {
                setSummary(e.target.value);
              }}
            />
          </Field>
          <Field
            label="Role instructions"
            hint="Who it is and how it works: its job, what it reads first, how it reports."
          >
            <Textarea
              rows={6}
              value={instructions}
              onChange={(e) => {
                setInstructions(e.target.value);
              }}
            />
          </Field>
          {workspaceId && (
            <ReadsPicker files={docFiles} reads={reads} onChange={setReads} />
          )}
          {workspaceId && (
            <Field
              label="Reports to"
              hint="Its place in the org chart: the Co-Founder, or another member (a sub-manager). Never a loop."
            >
              <Select
                value={reportsTo}
                onChange={(e) => {
                  setReportsTo(e.target.value);
                }}
              >
                <option value="">Co-Founder</option>
                {teammates
                  .filter((t) => t.name !== item?.name)
                  .map((t) => (
                    <option key={t.name} value={t.name}>
                      {t.title} (@{t.name})
                    </option>
                  ))}
              </Select>
            </Field>
          )}
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1.5 text-sm font-medium">
              {hiring ? "Model" : "Default model (optional)"}
            </legend>
            {hiring && (
              <p className="text-xs text-ink-3">
                Its version and reasoning effort, from this workspace&apos;s
                provider: small, repetitive work runs well on a small model with
                low effort; deep work needs a big one with high.
              </p>
            )}
            {model ? (
              <>
                <ModelPicker
                  catalog={catalog}
                  initial={model}
                  name="agentModel"
                  onChange={setModel}
                />
                {!hiring && (
                  <Button
                    variant="ghost"
                    className="self-start"
                    onClick={() => {
                      setModel(null);
                    }}
                  >
                    Use the task&apos;s model instead
                  </Button>
                )}
              </>
            ) : (
              <Button
                className="self-start"
                disabled={catalog.length === 0}
                onClick={() => {
                  const first = firstChoice(catalog);
                  if (first) setModel(first);
                }}
              >
                {hiring ? "Pick its model" : "Pick a default model"}
              </Button>
            )}
          </fieldset>
          {hiring && (
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-1.5 text-sm font-medium">
                Kit: what it needs to do the work well
              </legend>
              <p className="text-xs text-ink-3">
                Every new agent comes with its whole kit: at least one tool, one
                skill of this workspace, one doc or example, and a first test
                with what a good answer shows.
              </p>
              <KitEditor kit={kit} onChange={setKit} />
            </fieldset>
          )}
        </>
      )}
      {kind === "plugin" && (
        <>
          <Field
            label="Plugin name"
            hint="The plugin's own name. It stays disabled until a workspace turns it on."
          >
            <Input
              value={plugin}
              placeholder={name || "plugin_name"}
              onChange={(e) => {
                setPlugin(e.target.value);
              }}
            />
          </Field>
          <Field label="What it does">
            <Input
              value={summary}
              onChange={(e) => {
                setSummary(e.target.value);
              }}
            />
          </Field>
        </>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          disabled={busy}
          onClick={() => {
            setError(null);
            start(async () => {
              const result = await saveLibraryItem(
                kind,
                item?.id ?? null,
                draft(),
                workspaceId,
              );
              if (result.error) setError(result.error);
              else onDone();
            });
          }}
        >
          {item ? "Save changes" : `Create ${NOUN[kind]}`}
        </Button>
        {kind === "mcp" && item && workspaceId && (
          <Button
            disabled={busy}
            onClick={() => {
              start(async () => {
                setTest(await testMcp(item.id, workspaceId));
              });
            }}
          >
            Test connection
          </Button>
        )}
        <Button variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <FormStatus error={error} />
      </div>
      {test && (
        <p className={test.ok ? "text-sm text-success" : "text-sm text-danger"}>
          {test.ok
            ? `Connected. ${String((test.tools ?? []).length)} tool(s): ${(
                test.tools ?? []
              )
                .map((t) => t.name)
                .join(", ")}`
            : test.error}
        </p>
      )}
    </div>
  );
}

/** Which rule files (Documentation) the agent follows: given in full on every
 * job, or opened by itself when the work needs them (big files). */
function ReadsPicker({
  files,
  reads,
  onChange,
}: {
  files: DocChoice[];
  reads: Read[];
  onChange: (next: Read[]) => void;
}) {
  const find = (path: string) => reads.find((r) => r.path === path);
  function set(path: string, change: Partial<Read> | null) {
    const rest = reads.filter((r) => r.path !== path);
    if (change === null) {
      onChange(rest);
      return;
    }
    const now = find(path) ?? { path, section: "", mode: "always" as const };
    onChange([...rest, { ...now, ...change }]);
  }
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 text-sm font-medium">
        Reads (the rules it follows)
      </legend>
      <p className="text-xs text-ink-3">
        Picked files are given to it in full on every job (chat, task,
        automation), so it never forgets them. “When needed”: it opens them
        itself (for big files).
      </p>
      {files.length === 0 ? (
        <p className="text-sm text-ink-3">
          No rule files yet: add them in the Documentation tab.
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-line rounded-xl border border-line">
          {files.map((f) => {
            const r = find(f.path);
            return (
              <li
                key={f.path}
                className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm"
              >
                <label className="flex min-w-48 flex-1 items-center gap-2">
                  <input
                    type="checkbox"
                    checked={Boolean(r)}
                    onChange={(e) => {
                      set(f.path, e.target.checked ? {} : null);
                    }}
                  />
                  <span className="font-mono text-body-sm">{f.path}</span>
                </label>
                {r && (
                  <>
                    {f.sections.length > 0 && (
                      <select
                        className="rounded-lg border border-line bg-panel px-2 py-1 text-xs"
                        value={r.section}
                        onChange={(e) => {
                          set(f.path, { section: e.target.value });
                        }}
                      >
                        <option value="">Whole file</option>
                        {f.sections.map((s) => (
                          <option key={s} value={s.split(".")[0]}>
                            Section {s}
                          </option>
                        ))}
                      </select>
                    )}
                    <select
                      className="rounded-lg border border-line bg-panel px-2 py-1 text-xs"
                      value={r.mode}
                      onChange={(e) => {
                        set(f.path, {
                          mode:
                            e.target.value === "demand" ? "demand" : "always",
                        });
                      }}
                    >
                      <option value="always">Every job</option>
                      <option value="demand">When needed</option>
                    </select>
                  </>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </fieldset>
  );
}
