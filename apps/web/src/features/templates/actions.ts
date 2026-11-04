"use server";

import type { ModelSelection } from "@agos/core";
import { refresh } from "next/cache";
import type {
  AgentRevision,
  CatalogTeam,
  ImportPreview,
  ImportReport,
} from "@/data/types";
import { core, seg } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

export type Strategy = "skip" | "rename" | "replace";
export type Strategies = {
  agents: Strategy;
  skills: Strategy;
  automations: Strategy;
  vision: Strategy;
};

/** Where an import or a ready-made team goes, and what the owner chose. */
export type ImportChoices = {
  /** null: a new workspace (named `name`, on `defaultModel`). */
  workspaceId: string | null;
  name?: string;
  defaultModel?: ModelSelection | null;
  strategies: Strategies;
  /** The keys he typed (sent once, never shown again). */
  inputs: Record<string, string>;
  /** The keys he adds later in Workspace → Keys. */
  later: string[];
};

function body(choices: ImportChoices) {
  return {
    workspaceId: choices.workspaceId,
    name: choices.name ?? "",
    defaultModel: choices.defaultModel ?? null,
    strategies: choices.strategies,
    inputs: choices.inputs,
    later: choices.later,
  };
}

/** What a bundle holds and what of it the target workspace has already. */
export async function previewBundle(
  data: string,
  workspaceId: string | null,
): Promise<FormState & { preview?: ImportPreview }> {
  await requireAccess();
  let preview: ImportPreview | undefined;
  const result = await attempt(async () => {
    preview = await core<ImportPreview>("POST", "/import/preview", {
      data: String(data),
      workspaceId,
    });
  }, false);
  return { ...result, preview };
}

/** The bundle in, through AGOS's own writers; the fidelity report back. */
export async function importBundle(
  data: string,
  choices: ImportChoices,
): Promise<FormState & { report?: ImportReport }> {
  await requireAccess();
  let report: ImportReport | undefined;
  const result = await attempt(async () => {
    report = await core<ImportReport>("POST", "/import", {
      data: String(data),
      ...body(choices),
    });
  });
  refresh();
  return { ...result, report };
}

export async function listTemplates(): Promise<
  FormState & { teams?: CatalogTeam[] }
> {
  await requireAccess();
  let teams: CatalogTeam[] | undefined;
  const result = await attempt(async () => {
    teams = await core<CatalogTeam[]>("GET", "/templates");
  }, false);
  return { ...result, teams };
}

/** A ready-made team into a new workspace. */
export async function installTemplate(
  slug: string,
  choices: ImportChoices,
): Promise<FormState & { report?: ImportReport }> {
  await requireAccess();
  let report: ImportReport | undefined;
  const result = await attempt(async () => {
    report = await core<ImportReport>(
      "POST",
      `/templates/${seg(slug)}/install`,
      body(choices),
    );
  });
  refresh();
  return { ...result, report };
}

const revisions = (workspaceId: string, agentId: number) =>
  `/workspaces/${seg(workspaceId)}/agents/${seg(agentId)}/revisions`;

/** A member's revisions (read when its Revisions tab opens). */
export async function agentRevisions(
  workspaceId: string,
  agentId: number,
): Promise<FormState & { revisions?: AgentRevision[] }> {
  await requireAccess();
  let found: AgentRevision[] | undefined;
  const result = await attempt(async () => {
    found = await core<AgentRevision[]>("GET", revisions(workspaceId, agentId));
  }, false);
  return { ...result, revisions: found };
}

/** Back to vN: a new revision written through the team's own path. */
export async function restoreAgentRevision(
  workspaceId: string,
  agentId: number,
  n: number,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("POST", `${revisions(workspaceId, agentId)}/${seg(n)}/restore`),
  );
  refresh();
  return result;
}
