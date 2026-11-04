"use client";

import type { GoalPayload, PlanItem } from "../proposal-types";
import { Row } from "./row";
import { Eyebrow } from "@/shared/ui/eyebrow";

/** Today's plan: the owner's items and each member's; he drops or rewords any
 * before he accepts. */
export function DailyPlan({
  payload: g,
  edits,
  onEdit,
}: {
  payload: GoalPayload;
  edits: Record<string, unknown>;
  onEdit?: (edits: Record<string, unknown>) => void;
}) {
  const you = (edits.you as PlanItem[] | undefined) ?? g.you ?? [];
  const members = (edits.members as PlanItem[] | undefined) ?? g.members ?? [];
  const list = (key: "you" | "members", items: PlanItem[]) => (
    <ul className="flex flex-col gap-1">
      {items.map((item, n) => (
        <li
          key={`${key}-${String(n)}`}
          className="flex items-center gap-2 text-sm"
        >
          {key === "members" && (
            <span className="shrink-0 text-ink-3">@{item.member}</span>
          )}
          {onEdit ? (
            <input
              className="h-7 min-w-0 flex-1 rounded-md border border-line bg-panel px-2 text-sm"
              aria-label="Item"
              value={item.title}
              onChange={(e) => {
                const next = items.map((it, i) =>
                  i === n ? { ...it, title: e.target.value } : it,
                );
                onEdit({ ...edits, [key]: next });
              }}
            />
          ) : (
            <span className="min-w-0 flex-1">{item.title}</span>
          )}
          {onEdit && (
            <button
              type="button"
              className="text-xs text-ink-3 hover:text-danger"
              aria-label={`Drop ${item.title}`}
              onClick={() => {
                onEdit({ ...edits, [key]: items.filter((_it, i) => i !== n) });
              }}
            >
              ✕
            </button>
          )}
        </li>
      ))}
    </ul>
  );
  return (
    <div className="flex flex-col gap-2">
      <Row label="Day">{g.date}</Row>
      {g.summary && <Row label="In short">{g.summary}</Row>}
      <div>
        <Eyebrow>You</Eyebrow>
        {you.length > 0 ? (
          list("you", you)
        ) : (
          <p className="text-sm text-ink-3">Nothing.</p>
        )}
      </div>
      <div>
        <Eyebrow>The team</Eyebrow>
        {members.length > 0 ? (
          list("members", members)
        ) : (
          <p className="text-sm text-ink-3">Nothing.</p>
        )}
      </div>
    </div>
  );
}
