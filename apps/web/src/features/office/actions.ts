"use server";

import { refresh } from "next/cache";
import type { OfficeLook } from "@/data/types";
import { core, seg } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

/** Save how one agent looks in the Office ("cofounder" = the Co-Founder). */
export async function saveOfficeLook(
  workspaceId: string,
  member: string,
  look: OfficeLook,
): Promise<FormState> {
  await requireAccess();
  const body: OfficeLook = {
    pet: look.pet,
    petName: String(look.petName ?? "")
      .trim()
      .slice(0, 24),
    colour: look.colour,
    item: look.item,
  };
  const result = await attempt(() =>
    core("PUT", `/workspaces/${seg(workspaceId)}/office/${seg(member)}`, body),
  );
  refresh();
  return result;
}
