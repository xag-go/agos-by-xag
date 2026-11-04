"use server";

import { refresh } from "next/cache";
import type { DocFinding } from "@/data/queries";
import { core, seg } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

const docs = (id: string) => `/workspaces/${seg(id)}/docs`;
const file = (id: string, path: string) =>
  `${docs(id)}/file?path=${encodeURIComponent(path)}`;

export type SaveResult = FormState & { findings?: DocFinding[] };

/** Saves a rule file: a version and a CHANGES.md line (with why). */
export async function saveDoc(
  workspaceId: string,
  path: string,
  text: string,
  why: string,
  baseHash: string,
): Promise<SaveResult> {
  await requireAccess();
  if (!why.trim())
    return { error: "Say why you change it (it goes in CHANGES.md)." };
  let findings: SaveResult["findings"] = [];
  const result = await attempt(async () => {
    const r = await core<{ saved: boolean; findings: SaveResult["findings"] }>(
      "PUT",
      file(workspaceId, path),
      { text, why, base_hash: baseHash },
    );
    findings = r.findings;
  });
  refresh();
  return { ...result, findings };
}

export async function newDoc(
  workspaceId: string,
  path: string,
  why: string,
): Promise<FormState> {
  await requireAccess();
  const clean = path.trim().endsWith(".md") ? path.trim() : `${path.trim()}.md`;
  const result = await attempt(() =>
    core("POST", `${docs(workspaceId)}/file`, { path: clean, why }),
  );
  refresh();
  return result;
}

export async function deleteDoc(
  workspaceId: string,
  path: string,
  why: string,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core(
      "POST",
      `${docs(workspaceId)}/file/delete?path=${encodeURIComponent(path)}`,
      { why },
    ),
  );
  refresh();
  return result;
}

export async function versionDiff(
  workspaceId: string,
  versionId: number,
): Promise<{ diff: string; text: string } | null> {
  await requireAccess();
  try {
    return await core<{ diff: string; text: string }>(
      "GET",
      `${docs(workspaceId)}/versions/${String(versionId)}`,
    );
  } catch {
    return null;
  }
}

export async function restoreVersion(
  workspaceId: string,
  versionId: number,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("POST", `${docs(workspaceId)}/versions/${String(versionId)}/restore`, {
      why: "",
    }),
  );
  refresh();
  return result;
}

export async function setLatinOnly(
  workspaceId: string,
  on: boolean,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", `${docs(workspaceId)}/settings`, { latin_only: on }),
  );
  refresh();
  return result;
}

export async function restoreAgent(
  workspaceId: string,
  versionId: number,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core(
      "POST",
      `/workspaces/${seg(workspaceId)}/agents/versions/${String(versionId)}/restore`,
    ),
  );
  refresh();
  return result;
}
