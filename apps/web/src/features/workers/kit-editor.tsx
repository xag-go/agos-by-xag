"use client";

import { Button } from "@/shared/ui/button";
import { Input, Select, Textarea } from "@/shared/ui/field";
import type { Kit, KitDoc, KitSkill } from "./kit-types";
import { Eyebrow } from "@/shared/ui/eyebrow";

function RemoveButton({
  label,
  onClick,
}: {
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="grid size-9 shrink-0 place-items-center rounded-lg text-ink-3 transition-colors hover:bg-sunken hover:text-danger"
    >
      ×
    </button>
  );
}

/** The owner edits the kit before Approve (or gives a member one): add or
 * remove each tool, skill, doc, who it works with and its first test. */
export function KitEditor({
  kit,
  onChange,
}: {
  kit: Kit;
  onChange: (next: Kit) => void;
}) {
  const tools = kit.tools ?? [];
  const skills = kit.skills ?? [];
  const docs = kit.docs ?? [];
  const test = kit.onboarding ?? {};
  const set = (patch: Partial<Kit>) => {
    onChange({ ...kit, ...patch });
  };
  return (
    <div className="flex flex-col gap-3 rounded-xl bg-sunken/60 p-3">
      <section className="flex flex-col gap-1.5">
        <Eyebrow>Tools</Eyebrow>
        {tools.map((t, i) => (
          <div key={i} className="flex items-center gap-1.5">
            <Input
              aria-label="Tool"
              value={t.name}
              placeholder="Instagram"
              onChange={(e) => {
                set({
                  tools: tools.map((x, j) =>
                    j === i ? { ...x, name: e.target.value, connector: "" } : x,
                  ),
                });
              }}
            />
            <Input
              aria-label="API key name"
              className="w-44 font-mono text-xs"
              value={t.key ?? ""}
              placeholder={
                t.connector ? `connector ${t.connector}` : "KEY_NAME"
              }
              onChange={(e) => {
                set({
                  tools: tools.map((x, j) =>
                    j === i ? { ...x, key: e.target.value.toUpperCase() } : x,
                  ),
                });
              }}
            />
            <RemoveButton
              label={`Remove ${t.name || "tool"}`}
              onClick={() => {
                set({ tools: tools.filter((_, j) => j !== i) });
              }}
            />
          </div>
        ))}
        <Button
          variant="ghost"
          className="self-start"
          onClick={() => {
            set({ tools: [...tools, { name: "" }] });
          }}
        >
          + Tool
        </Button>
      </section>
      <section className="flex flex-col gap-1.5">
        <Eyebrow>Skills</Eyebrow>
        {skills.map((s, i) => (
          <div key={i} className="flex items-center gap-1.5">
            <Input
              aria-label="Skill"
              className="font-mono text-xs"
              value={s.name}
              placeholder="video-editing"
              onChange={(e) => {
                set({
                  skills: skills.map((x, j) =>
                    j === i ? { ...x, name: e.target.value.toLowerCase() } : x,
                  ),
                });
              }}
            />
            <Select
              aria-label="Where it comes from"
              className="w-40"
              value={s.source ?? "library"}
              onChange={(e) => {
                set({
                  skills: skills.map((x, j) =>
                    j === i
                      ? { ...x, source: e.target.value as KitSkill["source"] }
                      : x,
                  ),
                });
              }}
            >
              <option value="library">In the library</option>
              <option value="find">To find</option>
              <option value="write">To write</option>
            </Select>
            <RemoveButton
              label={`Remove ${s.name || "skill"}`}
              onClick={() => {
                set({ skills: skills.filter((_, j) => j !== i) });
              }}
            />
          </div>
        ))}
        <Button
          variant="ghost"
          className="self-start"
          onClick={() => {
            set({ skills: [...skills, { name: "", source: "find" }] });
          }}
        >
          + Skill
        </Button>
      </section>
      <section className="flex flex-col gap-1.5">
        <Eyebrow>Docs and examples</Eyebrow>
        {docs.map((d, i) => (
          <div key={i} className="flex items-center gap-1.5">
            <Input
              aria-label="File or link"
              className="font-mono text-xs"
              value={d.path || d.url || ""}
              placeholder="brand/style.md or https://…"
              onChange={(e) => {
                const v = e.target.value;
                const link = /^https?:\/\//.test(v);
                set({
                  docs: docs.map((x, j) =>
                    j === i
                      ? {
                          ...x,
                          path: link ? "" : v,
                          url: link ? v : "",
                          title: x.title,
                        }
                      : x,
                  ),
                });
              }}
            />
            <Select
              aria-label="Kind"
              className="w-32"
              value={d.kind ?? "doc"}
              onChange={(e) => {
                set({
                  docs: docs.map((x, j) =>
                    j === i
                      ? { ...x, kind: e.target.value as KitDoc["kind"] }
                      : x,
                  ),
                });
              }}
            >
              <option value="doc">Doc</option>
              <option value="example">Example</option>
            </Select>
            <RemoveButton
              label="Remove this file"
              onClick={() => {
                set({ docs: docs.filter((_, j) => j !== i) });
              }}
            />
          </div>
        ))}
        <Button
          variant="ghost"
          className="self-start"
          onClick={() => {
            set({ docs: [...docs, { path: "", kind: "doc" }] });
          }}
        >
          + Doc or example
        </Button>
      </section>
      <section className="grid grid-cols-2 gap-1.5">
        <Input
          aria-label="Works with"
          value={(kit.team?.works_with ?? []).join(", ")}
          placeholder="Works with: script-writer, …"
          onChange={(e) => {
            set({
              team: {
                ...kit.team,
                works_with: e.target.value
                  .split(",")
                  .map((x) => x.trim().replace(/^@/, ""))
                  .filter(Boolean),
              },
            });
          }}
        />
        <Input
          aria-label="Project"
          value={kit.team?.project ?? ""}
          placeholder="Project: weekly reels"
          onChange={(e) => {
            set({ team: { ...kit.team, project: e.target.value } });
          }}
        />
      </section>
      <section className="flex flex-col gap-1.5">
        <Eyebrow>First test</Eyebrow>
        <Textarea
          aria-label="Onboarding task"
          rows={2}
          className="min-h-0"
          value={test.task ?? ""}
          placeholder="A small real task, e.g. edit this 30 s clip in our style"
          onChange={(e) => {
            set({ onboarding: { ...test, task: e.target.value } });
          }}
        />
        <Textarea
          aria-label="Graded on (one per line)"
          rows={2}
          className="min-h-0"
          value={(test.criteria ?? []).join("\n")}
          placeholder="Graded on, one per line"
          onChange={(e) => {
            set({
              onboarding: { ...test, criteria: e.target.value.split("\n") },
            });
          }}
        />
      </section>
    </div>
  );
}
