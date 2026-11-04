"use server";

import { refresh } from "next/cache";
import { core } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

export async function addOwnerRule(text: string): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("POST", "/owner-rules", { text: String(text) }),
  );
  refresh();
  return result;
}

export async function editOwnerRule(
  id: number,
  text: string,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", `/owner-rules/${Number(id)}`, {
      text: String(text),
    }),
  );
  refresh();
  return result;
}

export async function deleteOwnerRule(id: number): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("DELETE", `/owner-rules/${Number(id)}`),
  );
  refresh();
  return result;
}

/** The AGOS Brain: ways of working shared by every workspace. */
export async function addMethod(text: string): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("POST", "/brain", { text: String(text) }),
  );
  refresh();
  return result;
}

export async function editMethod(id: number, text: string): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", `/brain/${Number(id)}`, { text: String(text) }),
  );
  refresh();
  return result;
}

export async function deleteMethod(id: number): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() => core("DELETE", `/brain/${Number(id)}`));
  refresh();
  return result;
}

/** On / "Not here" for one Brain method in one workspace. */
export async function setMethodHere(
  workspaceId: string,
  id: number,
  used: boolean,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core(
      "PUT",
      `/workspaces/${encodeURIComponent(workspaceId)}/brain/${Number(id)}`,
      { used },
    ),
  );
  refresh();
  return result;
}
