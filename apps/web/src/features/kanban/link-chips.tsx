"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import type { ExternalObject } from "@/data/types";
import { LinkChips } from "@/shared/ui/link-chips";
import { resolveLinks } from "./card-actions";

const LINK =
  /https:\/\/(?:github\.com|linear\.app|[a-z0-9-]+\.atlassian\.net)\/[^\s<>()]+[^\s<>().,;:!?'"]/g;

function normal(url: string): string {
  try {
    return new URL(url).href;
  } catch {
    return url;
  }
}

/** Reads the live state of every PR / issue / ticket the card's texts link,
 * once per opening; the card's Markdown shows those links as chips. */
export function LinkChipsProvider({
  workspaceId,
  texts,
  children,
}: {
  workspaceId: string;
  texts: string[];
  children: ReactNode;
}) {
  const urls = useMemo(
    () => [...new Set(texts.flatMap((t) => (t.match(LINK) ?? []).map(normal)))],
    [texts],
  );
  const [chips, setChips] = useState<ReadonlyMap<string, ExternalObject>>(
    new Map(),
  );
  const key = urls.join(" ");
  useEffect(() => {
    if (!key) return;
    let alive = true;
    void resolveLinks(workspaceId, key.split(" ")).then((found) => {
      if (alive) setChips(new Map(found.map((c) => [normal(c.url), c])));
    });
    return () => {
      alive = false;
    };
  }, [key, workspaceId]);
  return <LinkChips value={chips}>{children}</LinkChips>;
}
