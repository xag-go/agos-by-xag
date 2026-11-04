"use client";

import { useState, useTransition } from "react";
import type { Heartbeat } from "@/data/types";
import { setHeartbeat } from "@/features/setup/actions";
import { Select } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { Switch } from "@/shared/ui/switch";
import { formatWhen } from "@/shared/format";

const INTERVALS = [
  ["15m", "every 15 minutes"],
  ["1h", "every hour"],
  ["4h", "every 4 hours"],
  ["daily", "once a day"],
] as const;
type Interval = (typeof INTERVALS)[number][0];

/** The member's heartbeat (a Hermes cron job in its own profile): on with an
 * interval, or off; the last heartbeat from Hermes's executions ledger. */
export function HeartbeatField({
  workspaceId,
  agent,
  heartbeat,
}: {
  workspaceId: string;
  /** The member's name; "" for the Co-Founder. */
  agent: string;
  heartbeat: Heartbeat | undefined;
}) {
  const [busy, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const known = (heartbeat?.interval ?? "1h") as string;
  const [interval, setInterval] = useState<Interval>(
    INTERVALS.some(([id]) => id === known) ? (known as Interval) : "1h",
  );
  const on = heartbeat?.on ?? false;
  const save = (nextOn: boolean, nextInterval: Interval) => {
    setError(null);
    start(async () => {
      const r = await setHeartbeat(workspaceId, agent, nextOn, nextInterval);
      if (r.error) setError(r.error);
    });
  };
  return (
    <div className="flex flex-col gap-2 border-t border-line pt-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium">Heartbeat</p>
          <p className="text-xs text-ink-3">
            Wakes on its own to review its cards, its questions and proposals,
            {agent
              ? " the Co-Founder's requests and its inboxes"
              : " the team's blocked cards and the workspace's goal"}
            . Does only what is its; writes nothing when there is nothing to do.
          </p>
        </div>
        <Switch
          defaultOn={on}
          disabled={busy}
          label="Heartbeat on or off"
          onChange={(next) => save(next, interval)}
        />
      </div>
      {on && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-ink-3">
          <Select
            className="h-8 w-auto"
            value={interval}
            disabled={busy}
            onChange={(e) => {
              const next = e.target.value as Interval;
              setInterval(next);
              save(true, next);
            }}
          >
            {INTERVALS.map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </Select>
          <span>
            {heartbeat?.lastAt
              ? `Last heartbeat ${formatWhen(heartbeat.lastAt)}${heartbeat.lastStatus === "ok" ? "" : " (failed)"}`
              : "No heartbeat yet."}
            {heartbeat?.nextAt ? ` · next ${formatWhen(heartbeat.nextAt)}` : ""}
          </span>
          {heartbeat?.problem && (
            <span className="text-attention-ink">{heartbeat.problem}</span>
          )}
        </div>
      )}
      <FormStatus error={error} />
    </div>
  );
}
