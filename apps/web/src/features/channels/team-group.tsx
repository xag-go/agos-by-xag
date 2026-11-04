"use client";

import { useState, useTransition } from "react";
import type { TeamGroups } from "@/data/queries";
import { Button } from "@/shared/ui/button";
import { FormStatus } from "@/shared/ui/form-status";
import { Select } from "@/shared/ui/field";
import { setTeamGroup } from "./actions";

/**
 * The workspace's team group in Telegram: one group with Topics, where each chat
 * (an agent, a session, a team chat) gets its own topic, linked to it both ways.
 */
export function TeamGroup({
  workspaceId,
  groups,
}: {
  workspaceId: string;
  groups: TeamGroups;
}) {
  const [group, setGroup] = useState(groups.teamGroup);
  const [status, setStatus] = useState<{
    error: string | null;
    saved?: boolean;
  }>({
    error: null,
  });
  const [busy, start] = useTransition();
  const chosen = groups.groups.find((g) => g.id === groups.teamGroup);
  return (
    <div className="flex flex-col gap-3">
      <ol className="list-decimal space-y-1 pl-5 text-sm text-ink-2">
        <li>In Telegram, create a group and turn on Topics in its settings.</li>
        <li>
          Add this workspace&apos;s bot to it as an admin (allowed to manage
          topics).
        </li>
        <li>Write any message in the group: it shows up below.</li>
      </ol>
      {groups.groups.length === 0 ? (
        <p className="text-sm text-ink-3">No group seen yet.</p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <Select
            aria-label="Team group"
            value={group}
            onChange={(e) => {
              setGroup(e.target.value);
            }}
          >
            <option value="">None</option>
            {groups.groups.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </Select>
          <Button
            className="h-9"
            disabled={busy || group === groups.teamGroup}
            onClick={() => {
              start(async () => {
                const r = await setTeamGroup(workspaceId, group);
                setStatus({ error: r.error ?? null, saved: !r.error });
              });
            }}
          >
            Save
          </Button>
          <FormStatus error={status.error} saved={status.saved} />
        </div>
      )}
      {chosen && (
        <p className="text-sm text-ink-2">
          Team group:{" "}
          <span className="font-medium text-ink">{chosen.name}</span>. Give a
          chat its topic with “Telegram topic” in the chat&apos;s header.
        </p>
      )}
    </div>
  );
}
