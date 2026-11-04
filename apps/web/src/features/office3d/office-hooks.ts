import { useEffect, useState } from "react";
import type { KanbanCard, OfficeLook } from "@/data/types";
import { ownerOf } from "@/features/office/model";
import type { Activity } from "./controller";
import type { FeedEvent } from "./demo";
import { agoShort } from "@/shared/format";

export const ACCENTS: Record<OfficeLook["colour"], string> = {
  indigo: "#6f7fc9",
  teal: "#4f9c92",
  amber: "#d4a24c",
  rose: "#c9727f",
  violet: "#8f78c4",
  slate: "#6b7684",
  lime: "#8dae5a",
  sky: "#5aa2c8",
};

export const DOT: Record<Activity, string> = {
  working: "#5fbf7f",
  thinking: "#5fbf7f",
  waiting: "#e0574c",
  blocked: "#e0a33c",
  meeting: "#8f9be0",
  break: "#c9a45c",
  idle: "#9a958c",
  offline: "#5a5a5a",
};

let glCache: boolean | undefined;
export function webglAvailable(): boolean {
  if (glCache === undefined) {
    try {
      const c = document.createElement("canvas");
      glCache = !!(c.getContext("webgl2") ?? c.getContext("webgl"));
    } catch {
      glCache = false;
    }
  }
  return glCache;
}
export const noSubscribe = () => () => undefined;

export function ago(at: number) {
  const s = Math.max(0, Date.now() / 1000 - at);
  return agoShort(s) ?? `${String(Math.floor(s / 86400))}d`;
}

/** Real events from the Kanban: new, started, finished. */
export function liveFeed(
  cards: KanbanCard[],
  names: Map<string, string>,
): FeedEvent[] {
  const out: FeedEvent[] = [];
  for (const c of cards) {
    const mine = ownerOf(c);
    const who = names.get(mine) ?? (c.memberTitle || "Co-Founder");
    if (c.completedAt && c.status === "done")
      out.push({
        at: c.completedAt,
        who,
        text: `finished “${c.title}”`,
        kind: "done",
        cardId: c.id,
      });
    if (c.startedAt)
      out.push({
        at: c.startedAt,
        who,
        text: `started “${c.title}”`,
        kind: "start",
        cardId: c.id,
      });
    if (c.status !== "archived")
      out.push({
        at: c.createdAt,
        who,
        text:
          mine === "cofounder" ? `took on “${c.title}”` : `got “${c.title}”`,
        kind: "new",
        cardId: c.id,
      });
  }
  return out.sort((a, b) => b.at - a.at).slice(0, 30);
}

export function usePrefersReducedMotion() {
  const [reduce, setReduce] = useState(false);
  useEffect(() => {
    const q = window.matchMedia("(prefers-reduced-motion: reduce)");
    const on = () => {
      setReduce(q.matches);
    };
    on();
    q.addEventListener("change", on);
    return () => {
      q.removeEventListener("change", on);
    };
  }, []);
  return reduce;
}

export function useHidden() {
  const [hidden, setHidden] = useState(false);
  useEffect(() => {
    const on = () => {
      setHidden(document.visibilityState === "hidden");
    };
    document.addEventListener("visibilitychange", on);
    return () => {
      document.removeEventListener("visibilitychange", on);
    };
  }, []);
  return hidden;
}
