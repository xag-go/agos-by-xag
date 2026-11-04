"use client";

import { useState, useTransition } from "react";
import type { CapabilityRequest } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { decideCapability } from "./actions";
import { Eyebrow } from "@/shared/ui/eyebrow";
import { Panel } from "@/shared/ui/panel";

const STATUS: Record<CapabilityRequest["status"], string> = {
  proposed: "Waiting for you",
  connecting: "Waiting for your login",
  done: "Done",
  rejected: "Refused",
  failed: "Didn't work",
};

/**
 * The Co-Founder asks to turn something on (or off) in this workspace. Nothing
 * changes until the owner approves; an app not connected yet opens its login.
 */
export function CapabilityCard({
  workspaceId,
  request: r,
}: {
  workspaceId: string;
  request: CapabilityRequest;
}) {
  const [busy, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const open = r.status === "proposed" || r.status === "failed";
  const decide = (approve: boolean) =>
    start(async () => {
      setError(null);
      const res = await decideCapability(workspaceId, r.id, approve);
      if (res.error) setError(res.error);
      else if (res.loginUrl) window.location.assign(res.loginUrl);
    });
  return (
    <Panel className="max-w-xl px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <Eyebrow>
          {r.turnOn ? "Turn on" : "Turn off"} · {r.kind}
        </Eyebrow>
        <span
          className={cn(
            "rounded-md px-1.5 py-0.5 text-xs font-medium",
            r.status === "proposed" && "bg-attention text-attention-ink",
            r.status === "connecting" && "text-ink ring-1 ring-ink ring-inset",
            r.status === "done" && "bg-sunken text-ink-2",
            r.status === "rejected" && "bg-sunken text-ink-3",
            r.status === "failed" && "bg-danger-soft text-danger",
          )}
        >
          {STATUS[r.status]}
        </span>
      </div>
      <p className="mt-1.5 text-sm">
        The Co-Founder asks to {r.turnOn ? "turn on" : "turn off"}{" "}
        <span className="font-medium">{r.title}</span> in this workspace.
      </p>
      {r.reason && <p className="mt-1 text-sm text-ink-2">{r.reason}</p>}
      {r.status === "failed" && r.error && (
        <p className="mt-1 text-sm text-danger">{r.error}</p>
      )}
      {error && (
        <p role="alert" className="mt-1 text-sm text-danger">
          {error}
        </p>
      )}
      {open && (
        <div className="mt-3 flex items-center gap-2">
          <Button
            type="button"
            variant="primary"
            disabled={busy}
            onClick={() => {
              decide(true);
            }}
          >
            {busy
              ? "Working…"
              : r.status === "failed"
                ? "Try again"
                : "Approve"}
          </Button>
          <Button
            type="button"
            variant="ghost"
            disabled={busy}
            onClick={() => {
              decide(false);
            }}
          >
            No
          </Button>
          {r.kind === "app" && r.turnOn && (
            <span className="text-xs text-ink-3">
              If it isn&apos;t connected yet, you log in to it once.
            </span>
          )}
        </div>
      )}
      {r.status === "connecting" && (
        <div className="mt-3 flex items-center gap-2">
          <Button
            type="button"
            variant="secondary"
            disabled={busy}
            onClick={() => {
              decide(true);
            }}
          >
            Open the login again
          </Button>
        </div>
      )}
    </Panel>
  );
}
