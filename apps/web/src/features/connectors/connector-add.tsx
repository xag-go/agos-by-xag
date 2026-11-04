"use client";

import { useEffect, useState, useTransition, type ReactNode } from "react";
import type { ComposioToolkit, WorkspaceApp } from "@/data/types";
import { SignIn } from "@/features/settings/sign-in";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { Modal } from "@/shared/ui/dialog";
import {
  composioLink,
  connectApp,
  composioToolkits,
  setWorkspaceApp,
} from "./actions";
import {
  importFromMachine,
  listOnThisMachine,
  type FoundItem,
} from "@/features/library/actions";
import { AppSetup, COMPOSIO, ComposioKey, Logo } from "./connector-composio";
import { Panel } from "@/shared/ui/panel";

const SHOWN = 12;

/** One search over everything that can be added to this workspace. */
export function AddPanel({
  workspaceId,
  apps,
  composioOn,
  onCustomMcp,
}: {
  workspaceId: string;
  apps: WorkspaceApp[];
  composioOn: boolean;
  onCustomMcp: () => void;
}) {
  const [query, setQuery] = useState("");
  const [toolkits, setToolkits] = useState<ComposioToolkit[] | null>(null);
  const [servers, setServers] = useState<FoundItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [setup, setSetup] = useState<string | null>(null);
  const [busy, start] = useTransition();
  useEffect(() => {
    let live = true;
    void listOnThisMachine("mcp", workspaceId).then((r) => {
      if (!live) return;
      setServers(r.items);
      if (r.error) setError(r.error);
    });
    return () => {
      live = false;
    };
  }, [workspaceId]);
  useEffect(() => {
    if (!composioOn) return;
    let live = true;
    void composioToolkits(workspaceId).then((r) => {
      if (!live) return;
      setToolkits(r.toolkits);
      if (r.error) setError(r.error);
    });
    return () => {
      live = false;
    };
  }, [workspaceId, composioOn]);
  const q = query.trim().toLowerCase();
  const has = (...texts: string[]) =>
    !q || texts.some((t) => t.toLowerCase().includes(q));
  const appHits = apps
    .filter((a) => has(a.title, a.name, a.description))
    .slice(0, q ? 60 : SHOWN);
  const serverHits = (servers ?? [])
    .filter((i) => !i.inLibrary && has(i.title, i.name, i.summary))
    .slice(0, q ? 50 : SHOWN);
  const toolkitHits = (toolkits ?? [])
    .filter((t) => has(t.name, t.slug, ...t.categories))
    .slice(0, q ? 48 : SHOWN);

  function connect(slug: string) {
    setError(null);
    const tab = window.open("about:blank", "_blank");
    start(async () => {
      const r = await composioLink(workspaceId, slug);
      if (r.error || !r.url) {
        tab?.close();
        setError(r.error ?? "Composio gave no sign-in page.");
        return;
      }
      if (tab) tab.location.href = r.url;
      else window.open(r.url, "_blank");
    });
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-sm font-medium">Add</h3>
        <Input
          type="search"
          placeholder="Search apps and MCP servers (instagram, notion, github…)"
          aria-label="Search apps and MCP servers"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
          }}
          className="h-8 max-w-96 flex-1"
        />
        <Button className="h-8" variant="secondary" onClick={onCustomMcp}>
          Custom MCP server
        </Button>
      </div>
      <FormStatus error={error} />
      {setup ? (
        <Modal
          label="Set up an app"
          onClose={() => {
            setSetup(null);
          }}
        >
          <AppSetup
            workspaceId={workspaceId}
            toolkit={toolkits?.find((t) => t.slug === setup)}
            slug={setup}
            onClose={() => {
              setSetup(null);
            }}
            onDone={() => {
              setToolkits(
                (all) =>
                  all?.map((x) =>
                    x.slug === setup ? { ...x, ready: true } : x,
                  ) ?? null,
              );
              setSetup(null);
            }}
          />
        </Modal>
      ) : null}
      <Panel as="ul" className="grid gap-x-6 sm:grid-cols-2">
        {appHits.map((a) => (
          <AddRow key={`app-${a.name}`} workspaceId={workspaceId} app={a} />
        ))}
        {toolkitHits.map((t) => (
          <li
            key={`cz-${t.slug}`}
            className="flex items-start gap-3 border-b border-line px-4 py-3"
          >
            <Logo toolkit={t} name={t.name} />
            <span className="min-w-0 flex-1">
              <span className="block font-medium">{t.name}</span>
              <span className="line-clamp-2 block text-sm text-ink-2">
                {t.ready
                  ? t.description
                  : "Needs your own developer app once: Set up, then Connect."}
              </span>
              <Source>Composio</Source>
            </span>
            <Button
              className="h-8"
              variant="secondary"
              disabled={busy}
              onClick={() => {
                if (t.ready) connect(t.slug);
                else setSetup(t.slug);
              }}
            >
              {t.ready ? "Connect" : "Set up"}
            </Button>
          </li>
        ))}
        {serverHits.map((item) => (
          <CatalogServer
            key={`mcp-${item.origin}`}
            workspaceId={workspaceId}
            item={item}
          />
        ))}
      </Panel>
      {appHits.length + toolkitHits.length + serverHits.length === 0 && (
        <p className="text-sm text-ink-3">
          {servers === null ? "Reading…" : "No match."}
        </p>
      )}
      <p className="text-xs text-ink-3">
        {composioOn
          ? "Composio apps go into this workspace's own Composio project. "
          : "Turn on Composio (its project key) to add its 1000+ apps here. "}
        You sign in with the account this workspace should use; other workspaces
        never see it. Search to see more.
      </p>
    </div>
  );
}

function Source({ children }: { children: ReactNode }) {
  return (
    <span className="mt-0.5 inline-block rounded bg-sunken px-1.5 py-0.5 text-xs text-ink-3">
      {children}
    </span>
  );
}

/** An MCP server from Hermes's catalog: added to this workspace in one click
 * (definition only; it asks for its own key afterwards if it needs one). */
function CatalogServer({
  workspaceId,
  item,
}: {
  workspaceId: string;
  item: FoundItem;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  return (
    <li className="flex items-start gap-3 border-b border-line px-4 py-3">
      <span
        aria-hidden
        className="grid size-9 shrink-0 place-items-center rounded-lg bg-sunken font-display text-sm font-semibold"
      >
        {item.title.slice(0, 1).toUpperCase()}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block font-medium">{item.title}</span>
        <span className="line-clamp-2 block text-sm text-ink-2">
          {item.locked ?? item.summary}
        </span>
        <Source>
          {item.trust === "Yours"
            ? "MCP · Your list (Settings)"
            : "MCP · Hermes's catalog"}
        </Source>
        <FormStatus error={error} className="mt-1" />
      </span>
      <Button
        className="h-8"
        variant="secondary"
        disabled={busy || !item.importable}
        onClick={() => {
          setError(null);
          start(async () => {
            const r = await importFromMachine("mcp", item.origin, workspaceId);
            if (r.error) setError(r.error);
          });
        }}
      >
        {busy ? "Adding…" : "Add"}
      </Button>
    </li>
  );
}

function AddRow({
  workspaceId,
  app: a,
}: {
  workspaceId: string;
  app: WorkspaceApp;
}) {
  const [error, setError] = useState<string | null>(a.error ?? null);
  const [busy, start] = useTransition();
  const status = a.locked
    ? a.locked
    : a.login === "none"
      ? "No login needed."
      : a.name === COMPOSIO
        ? "Use this workspace's own Composio project key (or Connect with a Composio login)."
        : "Not connected here";
  return (
    <li className="flex items-start gap-3 border-b border-line px-4 py-3 last:border-b-0">
      <span
        aria-hidden
        className="grid size-9 shrink-0 place-items-center rounded-lg bg-sunken font-display text-sm font-semibold"
      >
        {a.title.slice(0, 1)}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block font-medium">{a.title}</span>
        <span className="line-clamp-2 block text-sm text-ink-2">
          {a.description}
        </span>
        <span className="block text-xs text-ink-3">{status}</span>
        <Source>App</Source>
        <FormStatus error={error} className="mt-1" />
        {a.kind === "nous" && !a.connected && (
          <span className="mt-2 block max-w-md">
            <SignIn login={{ id: "nous", label: "Sign in to Nous Portal" }} />
          </span>
        )}
        {a.name === COMPOSIO && !a.locked && (
          <ComposioKey workspaceId={workspaceId} />
        )}
      </span>
      {a.kind === "catalog" && !a.locked && a.login === "oauth" && (
        <Button
          className="h-8"
          variant="secondary"
          disabled={busy}
          onClick={() => {
            setError(null);
            start(async () => {
              const r = await connectApp(workspaceId, a.name);
              if (r.error || !r.url) {
                setError(r.error ?? "The login didn't start.");
                return;
              }
              window.location.assign(r.url);
            });
          }}
        >
          {busy ? "Opening…" : "Connect"}
        </Button>
      )}
      {a.kind === "catalog" && !a.locked && a.login === "none" && (
        <Button
          className="h-8"
          variant="secondary"
          disabled={busy}
          onClick={() => {
            setError(null);
            start(async () => {
              const r = await setWorkspaceApp(workspaceId, a.name, true);
              if (r.error) setError(r.error);
            });
          }}
        >
          Turn on
        </Button>
      )}
    </li>
  );
}
