"use client";

import { useState, useTransition } from "react";
import { Button } from "@/shared/ui/button";
import { useAsk } from "@/shared/ui/confirm";
import { removeScheduled } from "./actions";

export function OngoingStop({
  workspaceId,
  id,
  label,
}: {
  workspaceId: string;
  id: string;
  label: string;
}) {
  const { dialog, confirm } = useAsk();
  const [busy, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="flex flex-col items-end gap-1">
      {dialog}
      <Button
        disabled={busy}
        onClick={() => {
          void (async () => {
            const yes = await confirm({
              title: "Stop this?",
              body: `“${label.slice(0, 200)}”: the agent won't do it anymore.`,
              confirmLabel: "Stop",
              danger: true,
            });
            if (!yes) return;
            setError(null);
            start(async () => {
              const r = await removeScheduled(workspaceId, id);
              if (r.error) setError(r.error);
            });
          })();
        }}
      >
        Stop
      </Button>
      {error ? (
        <span role="alert" className="text-xs text-danger">
          {error}
        </span>
      ) : null}
    </div>
  );
}
