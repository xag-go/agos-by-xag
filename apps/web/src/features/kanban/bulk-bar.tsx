"use client";

import { useState, useTransition } from "react";
import { Button } from "@/shared/ui/button";
import { Input, Select } from "@/shared/ui/field";
import { bulkCards, type BulkAction } from "./board-actions";
import type { BoardLabel } from "./labels";
import type { Member } from "./board-toolbar";

export function BulkBar({
  workspaceId,
  selected,
  all,
  onSelect,
  labels,
  members,
}: {
  workspaceId: string;
  selected: string[];
  all: string[];
  onSelect: (ids: string[]) => void;
  labels: BoardLabel[];
  members: Member[];
}) {
  const [busy, start] = useTransition();
  const [said, setSaid] = useState<string | null>(null);
  const [summary, setSummary] = useState("");
  const run = (
    action: BulkAction,
    extra: Parameters<typeof bulkCards>[3] = {},
  ) => {
    start(async () => {
      const r = await bulkCards(workspaceId, selected, action, extra);
      setSaid(r.error ?? `Done on ${String(r.done?.length ?? 0)} card(s).`);
      if (!r.error) onSelect([]);
    });
  };
  const none = selected.length === 0;
  return (
    <div
      role="toolbar"
      aria-label="Selected cards"
      className="flex flex-wrap items-center gap-2 rounded-xl border border-ink bg-panel px-3 py-2 text-sm"
    >
      <span className="font-medium">{selected.length} selected</span>
      <Button
        variant="ghost"
        onClick={() => {
          onSelect(selected.length === all.length ? [] : all);
        }}
      >
        {selected.length === all.length && all.length > 0
          ? "Select none"
          : "Select all shown"}
      </Button>
      <Select
        aria-label="Assign to"
        className="w-40 max-md:h-11 max-md:min-w-0 max-md:flex-1"
        disabled={busy || none}
        value=""
        onChange={(e) => {
          run("assign", {
            member: e.target.value === "-" ? "" : e.target.value,
          });
        }}
      >
        <option value="">Assign to…</option>
        {members.map((m) => (
          <option key={m.name} value={m.name}>
            {m.title}
          </option>
        ))}
        <option value="-">Nobody</option>
      </Select>
      {labels.length > 0 && (
        <>
          <Select
            aria-label="Add label"
            className="w-36 max-md:h-11 max-md:min-w-0 max-md:flex-1"
            disabled={busy || none}
            value=""
            onChange={(e) => {
              run("label", { add: [Number(e.target.value)] });
            }}
          >
            <option value="">Add label…</option>
            {labels.map((l) => (
              <option key={l.id} value={String(l.id)}>
                {l.name}
              </option>
            ))}
          </Select>
          <Select
            aria-label="Remove label"
            className="w-40 max-md:h-11 max-md:min-w-0 max-md:flex-1"
            disabled={busy || none}
            value=""
            onChange={(e) => {
              run("label", { remove: [Number(e.target.value)] });
            }}
          >
            <option value="">Remove label…</option>
            {labels.map((l) => (
              <option key={l.id} value={String(l.id)}>
                {l.name}
              </option>
            ))}
          </Select>
        </>
      )}
      <Select
        aria-label="Move"
        className="w-36 max-md:h-11 max-md:min-w-0 max-md:flex-1"
        disabled={busy || none}
        value=""
        onChange={(e) => {
          const action = e.target.value as BulkAction;
          if (action !== "done") {
            run(action);
          } else if (summary.trim()) {
            run("done", { summary });
          } else {
            setSaid("Write what was done (beside), then pick Mark done again.");
          }
        }}
      >
        <option value="">Move…</option>
        <option value="unblock">Unblock</option>
        <option value="block">Stop (block)</option>
        <option value="done">Mark done</option>
        <option value="archive">Archive</option>
      </Select>
      <Input
        aria-label="What was done (for Mark done)"
        placeholder="What was done (Mark done)"
        className="w-56 max-md:h-11 max-md:w-full"
        value={summary}
        onChange={(e) => {
          setSummary(e.target.value);
        }}
      />
      {said && <span className="text-ink-2">{said}</span>}
    </div>
  );
}
