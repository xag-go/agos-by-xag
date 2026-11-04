"use client";

import { useState, useTransition } from "react";
import type {
  KanbanMember,
  LibraryItem,
  SkillTests,
  SkillVersion,
} from "@/data/types";
import { FormStatus } from "@/shared/ui/form-status";
import { Switch } from "@/shared/ui/switch";
import { Tabs } from "@/shared/ui/tabs";
import { setSkillAutoUpdate } from "./skill-studio-actions";
import { VersionsTab } from "./skill-versions";
import { TestsTab } from "./skill-tests";
import { Panel } from "@/shared/ui/panel";

/** Skill Studio: one workspace skill's Versions (Hermes's skill ledger, diff,
 * restore) and Tests (saved inputs, a run template, runs as Hermes Kanban cards,
 * the grader's verdict). Each tab is one read, taken when the page opens. */
export function SkillStudio({
  workspaceId,
  item,
  versions,
  tests,
  members,
}: {
  workspaceId: string;
  item: LibraryItem;
  versions: SkillVersion[];
  tests: SkillTests;
  members: KanbanMember[];
}) {
  return (
    <div className="flex flex-col gap-4">
      {item.source === "web" && (
        <AutoUpdateRow workspaceId={workspaceId} item={item} />
      )}
      <Panel>
        <Tabs
          items={[
            {
              id: "versions",
              label: "Versions",
              count: versions.length,
              content: (
                <VersionsTab
                  workspaceId={workspaceId}
                  itemId={item.id}
                  initial={versions}
                />
              ),
            },
            {
              id: "tests",
              label: "Tests",
              count: tests.runs.length,
              content: (
                <TestsTab
                  workspaceId={workspaceId}
                  itemId={item.id}
                  initial={tests}
                  members={members}
                />
              ),
            },
          ]}
        />
      </Panel>
    </div>
  );
}

function AutoUpdateRow({
  workspaceId,
  item,
}: {
  workspaceId: string;
  item: LibraryItem;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  const on = item.definition.auto_update === true;
  return (
    <Panel className="flex flex-wrap items-center gap-3 px-5 py-3">
      <div className="min-w-60 flex-1">
        <p className="text-sm font-medium">Follow its source</p>
        <p className="text-xs text-ink-3">
          Nightly, this workspace&apos;s Hermes updates it from where it was
          installed; each update is a version here.
        </p>
      </div>
      <Switch
        defaultOn={on}
        disabled={busy}
        label="Follow its source"
        onChange={(next) => {
          setError(null);
          start(async () => {
            const result = await setSkillAutoUpdate(workspaceId, item.id, next);
            if (result.error) setError(result.error);
          });
        }}
      />
      <FormStatus error={error} className="w-full" />
    </Panel>
  );
}
