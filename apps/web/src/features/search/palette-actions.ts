"use server";

import { redirect } from "next/navigation";
import { refresh } from "next/cache";
import {
  getAutomations,
  getHeartbeats,
  getInbox,
  getWorkspaces,
} from "@/data/queries";
import type { SearchPage } from "@/data/types";
import { core, seg } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

export type PaletteData = {
  workspaces: { id: string; name: string }[];
  automations: { id: number; name: string; on: boolean }[];
  /** The newest Inbox item that one Approve settles (a proposal or a review). */
  top: {
    key: string;
    title: string;
    kind: "proposal" | "review";
    askId: number | null;
    card: string;
  } | null;
  heartbeat: { on: boolean; interval: string } | null;
};

/** What the palette lists besides its fixed actions, read when it opens (one
 * round: the core's own reads, nothing kept in the browser). */
export async function paletteData(workspaceId: string): Promise<PaletteData> {
  await requireAccess();
  const [workspaces, automations, inbox, heartbeats] = await Promise.all([
    getWorkspaces().catch(() => []),
    getAutomations(workspaceId).catch(() => []),
    getInbox(workspaceId).catch(() => null),
    getHeartbeats(workspaceId).catch(() => null),
  ]);
  const first = (inbox?.items ?? []).find(
    (i) =>
      !i.dismissed &&
      ((i.type === "proposal" && i.key.startsWith("ask:")) ||
        (i.type === "review" &&
          (i.review?.ownerCan ?? []).includes("approve"))),
  );
  const own = heartbeats?.find((h) => h.agent === "");
  return {
    workspaces: workspaces
      .filter((w) => !w.archived)
      .map((w) => ({ id: w.id, name: w.name })),
    automations: automations.map((a) => ({ id: a.id, name: a.name, on: a.on })),
    top: first
      ? {
          key: first.key,
          title: first.title,
          kind: first.type === "proposal" ? "proposal" : "review",
          askId:
            first.type === "proposal"
              ? Number(first.key.slice(4)) || null
              : null,
          card: first.card ?? "",
        }
      : null,
    heartbeat: own ? { on: own.on, interval: own.interval ?? "1h" } : null,
  };
}

export type PaletteHit = {
  type: string;
  title: string;
  where: string;
  href: string;
};

/** The palette's live results: the same search as the Search page, top hits. */
export async function paletteSearch(
  workspaceId: string,
  query: string,
): Promise<PaletteHit[]> {
  await requireAccess();
  const q = query.trim().slice(0, 200);
  if (q.length < 2) return [];
  const found = await core<SearchPage>(
    "GET",
    `/workspaces/${seg(workspaceId)}/search?q=${encodeURIComponent(q)}`,
  ).catch(() => null);
  return (found?.results ?? []).slice(0, 8).map((r) => ({
    type: r.type,
    title: r.title,
    where: r.where ?? "",
    href: r.href,
  }));
}

/** The Co-Founder's heartbeat on (at its interval) or off. */
export async function setCofounderHeartbeat(
  workspaceId: string,
  on: boolean,
  interval: string,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", `/workspaces/${seg(workspaceId)}/heartbeats/cofounder`, {
      on,
      interval: ["15m", "1h", "4h", "daily"].includes(interval)
        ? interval
        : "1h",
    }),
  );
  refresh();
  return result;
}

/** Hire: the Co-Founder is asked for a hire proposal (its DM, his words). */
export async function askToHire(
  workspaceId: string,
  role: string,
): Promise<void> {
  await requireAccess();
  const { id } = await core<{ id: number }>(
    "POST",
    `/workspaces/${seg(workspaceId)}/workers/dm`,
    { agent: "" },
  );
  const what = role.trim().slice(0, 300);
  await core(
    "POST",
    `/workspaces/${seg(workspaceId)}/chats/${seg(id)}/messages`,
    {
      body: what
        ? `I want to hire: ${what}. Propose the hire (role, lead, skills).`
        : "I want to hire someone new. Ask me what for, then propose the hire.",
      attachments: [],
    },
  );
  redirect(`/w/${workspaceId}/messages?c=${String(id)}`);
}
