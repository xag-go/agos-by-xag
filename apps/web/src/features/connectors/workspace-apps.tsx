"use client";

import { useState, useTransition, type ReactNode } from "react";
import type { WorkspaceApp } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { useAsk } from "@/shared/ui/confirm";
import { FormStatus } from "@/shared/ui/form-status";
import { Switch } from "@/shared/ui/switch";
import { disconnectApp, setWorkspaceApp } from "./actions";
import { COMPOSIO, ComposioApps, ComposioKey } from "./connector-composio";
import { AddPanel } from "./connector-add";
import { Panel } from "@/shared/ui/panel";

/** A workspace's connectors in one place: what is connected here (apps, its
 * Composio apps, its MCP servers) and one search to add more (AGOS apps, Composio's
 * apps, Hermes's MCP catalog, or a custom MCP server). Everything is this
 * workspace's own: other workspaces never see it. */
export function ConnectorsHub({
  workspaceId,
  apps,
  servers,
  onCustomMcp,
}: {
  workspaceId: string;
  apps: WorkspaceApp[];
  /** This workspace's MCP servers, already rendered as rows. */
  servers: ReactNode[];
  onCustomMcp: () => void;
}) {
  // An app with no login is "connected" only once it is on here.
  const here = (a: WorkspaceApp) =>
    a.connected && !a.locked && (a.login !== "none" || a.on);
  const ready = apps.filter(here);
  const composioOn = ready.some((a) => a.name === COMPOSIO && a.via === "key");
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h3 className="text-sm font-medium">Connected here</h3>
        {ready.length === 0 && servers.length === 0 ? (
          <p className="text-sm text-ink-3">Nothing connected yet.</p>
        ) : (
          <Panel as="ul" className="divide-y divide-line">
            {ready.map((a) => (
              <ConnectedRow key={a.name} workspaceId={workspaceId} app={a} />
            ))}
            {servers}
          </Panel>
        )}
      </div>
      <AddPanel
        workspaceId={workspaceId}
        apps={apps.filter((a) => !here(a))}
        composioOn={composioOn}
        onCustomMcp={onCustomMcp}
      />
    </div>
  );
}

function ConnectedRow({
  workspaceId,
  app: a,
}: {
  workspaceId: string;
  app: WorkspaceApp;
}) {
  const [error, setError] = useState<string | null>(a.error ?? null);
  const [busy, start] = useTransition();
  const { dialog, confirm } = useAsk();
  const label =
    a.kind === "nous"
      ? "App · your Nous account"
      : a.login === "none"
        ? "App · no login"
        : a.via === "key"
          ? `App · this workspace's own Composio project (${a.account ?? "key"})`
          : a.account
            ? `App · ${a.account}`
            : "App · connected here";
  return (
    <li className="px-5 py-3.5">
      {dialog}
      <div className="grid items-center gap-x-6 gap-y-1 sm:grid-cols-[12rem_1fr_auto_auto]">
        <span className="font-medium">{a.title}</span>
        <span className="text-sm text-ink-2">
          <span className="block text-xs text-ink-3">{label}</span>
          <span className="line-clamp-2">{a.description}</span>
        </span>
        {a.kind === "catalog" && a.login === "oauth" ? (
          <Button
            className="h-8"
            variant="ghost"
            disabled={busy}
            onClick={() => {
              void (async () => {
                setError(null);
                if (
                  !(await confirm({
                    title: `Disconnect ${a.title}?`,
                    body:
                      a.via === "key"
                        ? "This workspace forgets its Composio key. Its apps stay in its Composio project."
                        : "This workspace forgets its login. Other workspaces keep theirs.",
                    confirmLabel: "Disconnect",
                    danger: true,
                  }))
                )
                  return;
                start(async () => {
                  const r = await disconnectApp(workspaceId, a.name);
                  if (r.error) setError(r.error);
                });
              })();
            }}
          >
            Disconnect
          </Button>
        ) : (
          <span />
        )}
        <Switch
          defaultOn={a.on}
          label={`${a.title} on or off`}
          onChange={(on) => {
            setError(null);
            start(async () => {
              const result = await setWorkspaceApp(workspaceId, a.name, on);
              if (result.error) setError(result.error);
            });
          }}
        />
      </div>
      <FormStatus error={error} className="mt-1" />
      {a.name === COMPOSIO && a.via === "key" && (
        <>
          <ComposioApps workspaceId={workspaceId} />
          <ComposioKey workspaceId={workspaceId} replace />
        </>
      )}
    </li>
  );
}
