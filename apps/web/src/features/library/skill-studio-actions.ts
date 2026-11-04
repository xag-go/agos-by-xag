"use server";

import { refresh } from "next/cache";
import type { FileDiff, SkillTests, SkillVersion } from "@/data/types";
import { core, seg } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

// Skill Studio: a workspace skill's versions (Hermes's skill ledger), its test
// runs (Hermes Kanban cards) and its auto-update flag (a Hermes cron job). Every
// change goes to the core; the web keeps nothing.

const base = (workspaceId: string, itemId: number) =>
  `/workspaces/${seg(workspaceId)}/skills/${seg(itemId)}`;

/** Fresh reads after a change (the tabs refetch instead of a full page render). */
export async function readSkillVersions(
  workspaceId: string,
  itemId: number,
): Promise<SkillVersion[]> {
  await requireAccess();
  return core<SkillVersion[]>("GET", `${base(workspaceId, itemId)}/versions`);
}

export async function readSkillVersionDiff(
  workspaceId: string,
  itemId: number,
  a: number,
  b: number,
): Promise<FileDiff[]> {
  await requireAccess();
  return core<FileDiff[]>(
    "GET",
    `${base(workspaceId, itemId)}/versions/diff?a=${seg(a)}&b=${seg(b)}`,
  );
}

export async function readSkillTests(
  workspaceId: string,
  itemId: number,
): Promise<SkillTests> {
  await requireAccess();
  return core<SkillTests>("GET", `${base(workspaceId, itemId)}/tests`);
}

export type RestoreState = FormState & {
  restored?: boolean;
  version?: number;
  skipped?: string[];
};

/** One Hermes skill_manage batch makes the folder that version (the ledger
 * records it as the next version); already that: nothing written. */
export async function restoreSkillVersion(
  workspaceId: string,
  itemId: number,
  number: number,
): Promise<RestoreState> {
  await requireAccess();
  type Found = { restored: boolean; version: number; skipped: string[] };
  let found: Found | undefined;
  const result = await attempt(async () => {
    found = await core<Found>(
      "POST",
      `${base(workspaceId, itemId)}/versions/${seg(number)}/restore`,
    );
  });
  refresh();
  if (found === undefined) return result;
  const { restored, version, skipped } = found;
  return { ...result, restored, version, skipped };
}

export async function saveSkillTestSettings(
  workspaceId: string,
  itemId: number,
  template: string,
  checklist: string,
): Promise<FormState> {
  await requireAccess();
  return attempt(() =>
    core("PUT", `${base(workspaceId, itemId)}/tests/settings`, {
      template: template.slice(0, 20_000),
      checklist: checklist.slice(0, 20_000),
    }),
  );
}

export async function addSkillTestInput(
  workspaceId: string,
  itemId: number,
  input: { name: string; text: string; expected: string },
): Promise<FormState & { id?: number }> {
  await requireAccess();
  let id: number | undefined;
  const result = await attempt(async () => {
    ({ id } = await core<{ id: number }>(
      "POST",
      `${base(workspaceId, itemId)}/tests/inputs`,
      {
        name: input.name.trim().slice(0, 120),
        text: input.text.slice(0, 20_000),
        expected: input.expected.slice(0, 20_000),
      },
    ));
  });
  return { ...result, id };
}

export async function updateSkillTestInput(
  workspaceId: string,
  itemId: number,
  inputId: number,
  input: { name: string; text: string; expected: string },
): Promise<FormState> {
  await requireAccess();
  return attempt(() =>
    core("PUT", `${base(workspaceId, itemId)}/tests/inputs/${seg(inputId)}`, {
      name: input.name.trim().slice(0, 120),
      text: input.text.slice(0, 20_000),
      expected: input.expected.slice(0, 20_000),
    }),
  );
}

export async function deleteSkillTestInput(
  workspaceId: string,
  itemId: number,
  inputId: number,
): Promise<FormState> {
  await requireAccess();
  return attempt(() =>
    core("DELETE", `${base(workspaceId, itemId)}/tests/inputs/${seg(inputId)}`),
  );
}

/** A Hermes Kanban card for the member, with the skill loaded and pinned. */
export async function runSkillTest(
  workspaceId: string,
  itemId: number,
  inputId: number,
  member: string,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("POST", `${base(workspaceId, itemId)}/tests/run`, {
      inputId,
      member: member.slice(0, 64),
    }),
  );
  refresh();
  return result;
}

export async function rerunSkillTest(
  workspaceId: string,
  itemId: number,
  runId: number,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("POST", `${base(workspaceId, itemId)}/tests/runs/${seg(runId)}/rerun`),
  );
  refresh();
  return result;
}

export async function gradeSkillTest(
  workspaceId: string,
  itemId: number,
  runId: number,
): Promise<FormState> {
  await requireAccess();
  return attempt(() =>
    core("POST", `${base(workspaceId, itemId)}/tests/runs/${seg(runId)}/grade`),
  );
}

/** Follow the source: the workspace's Hermes cron job updates it nightly. */
export async function setSkillAutoUpdate(
  workspaceId: string,
  itemId: number,
  on: boolean,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", `${base(workspaceId, itemId)}/auto-update`, { on }),
  );
  refresh();
  return result;
}
