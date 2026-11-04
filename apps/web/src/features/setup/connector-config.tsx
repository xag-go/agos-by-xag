"use client";

import { useState, useTransition } from "react";
import type { Connector, LibraryKind, McpTest } from "@/data/types";
import {
  setConnector,
  setConnectorSecret,
  startMcpSignIn,
  mcpSignInStatus,
  mcpSignOut,
  testMcp,
} from "@/features/library/actions";
import { Button } from "@/shared/ui/button";
import { Input, Textarea } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";

export const kindLabels: Record<
  LibraryKind,
  { title: string; local: string; empty: string }
> = {
  skill: {
    title: "Skills",
    local: "Notes (only you see these)",
    empty:
      "No skills yet. Create one, or add one from this machine, the web or another workspace.",
  },
  agent: {
    title: "Agents",
    local: "Instructions (this workspace)",
    empty: "No agents yet. Create them in this workspace's Hierarchy.",
  },
  mcp: {
    title: "MCP servers",
    local: "Notes (this workspace)",
    empty: "",
  },
  tool: { title: "Tools", local: "Notes (this workspace)", empty: "" },
  plugin: {
    title: "Plugins",
    local: "Configuration notes (this workspace)",
    empty: "No plugins yet. Add them in Settings → Plugins.",
  },
};

export function ConnectorConfig({
  workspaceId,
  connector: c,
}: {
  workspaceId: string;
  connector: Connector;
}) {
  const [local, setLocal] = useState(c.local);
  const [tools, setTools] = useState<string[]>(c.allowedTools);
  const [secret, setSecret] = useState("");
  const [found, setFound] = useState<McpTest | null>(null);
  const [status, setStatus] = useState<{
    error: string | null;
    saved: boolean;
  }>({ error: null, saved: false });
  const [busy, start] = useTransition();

  function save() {
    setStatus({ error: null, saved: false });
    start(async () => {
      const result = await setConnector(
        workspaceId,
        c.itemId,
        c.on,
        tools,
        local,
      );
      setStatus({ error: result.error, saved: !result.error });
    });
  }

  return (
    <div className="mt-3 flex flex-col gap-4 rounded-xl border border-line bg-sunken/40 p-4">
      <label className="flex flex-col gap-1.5">
        <span className="text-sm font-medium">{kindLabels[c.kind].local}</span>
        <Textarea
          rows={3}
          value={local}
          onChange={(e) => {
            setLocal(e.target.value);
          }}
          placeholder="Only this workspace sees this."
        />
      </label>

      {c.kind === "mcp" && (
        <>
          <SignInRow workspaceId={workspaceId} connector={c} />
          {c.needsSecret && (
            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">
                Or a key for this workspace (API key / agent key)
              </span>
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  type="password"
                  autoComplete="off"
                  value={secret}
                  placeholder={c.secret ?? "Paste the token or API key"}
                  onChange={(e) => {
                    setSecret(e.target.value);
                  }}
                  className="max-w-sm"
                  aria-label="Credential"
                />
                <Button
                  disabled={busy || !secret.trim()}
                  onClick={() => {
                    start(async () => {
                      const result = await setConnectorSecret(
                        workspaceId,
                        c.itemId,
                        secret,
                      );
                      setSecret("");
                      setStatus({ error: result.error, saved: !result.error });
                    });
                  }}
                >
                  Save credential
                </Button>
                {c.secret && (
                  <Button
                    variant="ghost"
                    disabled={busy}
                    onClick={() => {
                      start(async () => {
                        const result = await setConnectorSecret(
                          workspaceId,
                          c.itemId,
                          null,
                        );
                        setStatus({
                          error: result.error,
                          saved: !result.error,
                        });
                      });
                    }}
                  >
                    Remove
                  </Button>
                )}
              </div>
              <span className="text-xs text-ink-3">
                Sent as “Authorization: Bearer …” unless the server says
                otherwise in Settings → Connectors. Encrypted, shown only as its
                last 4 characters.
              </span>
            </div>
          )}
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">Allowed tools</span>
              <Button
                className="h-8"
                disabled={busy}
                onClick={() => {
                  start(async () => {
                    setFound(await testMcp(c.itemId, workspaceId));
                  });
                }}
              >
                Test connection
              </Button>
            </div>
            {found && !found.ok && (
              <p className="text-sm text-danger">{found.error}</p>
            )}
            {found?.ok && (
              <ul className="grid gap-1.5 sm:grid-cols-2">
                {(found.tools ?? []).map((t) => (
                  <li key={t.name}>
                    <label className="flex items-start gap-2 text-sm">
                      <input
                        type="checkbox"
                        className="mt-1 accent-accent"
                        checked={tools.includes(t.name)}
                        onChange={(e) => {
                          const name = t.name;
                          setTools((list) =>
                            e.target.checked
                              ? [...list, name]
                              : list.filter((x) => x !== name),
                          );
                        }}
                      />
                      <span>
                        <span className="font-mono text-xs">{t.name}</span>
                        <span className="block text-xs text-ink-3">
                          {t.description}
                        </span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            )}
            <span className="text-xs text-ink-3">
              {tools.length === 0
                ? "No limit: every tool of the server is allowed."
                : `Only these: ${tools.join(", ")}`}
            </span>
          </div>
        </>
      )}

      <div className="flex items-center gap-3">
        <Button variant="primary" disabled={busy} onClick={save}>
          Save
        </Button>
        <FormStatus error={status.error} saved={status.saved} />
      </div>
    </div>
  );
}

/** OAuth sign-in for this workspace only: the server's own login page opens in
 * a new tab; once you allow it, the agents get its tools. No terminal. */
function SignInRow({
  workspaceId,
  connector: c,
}: {
  workspaceId: string;
  connector: Connector;
}) {
  const signedIn = c.secret === "signed in (OAuth)";
  const [state, setState] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();

  function poll(tries: number) {
    if (tries <= 0) {
      setState(null);
      setError("Still not signed in. Try again.");
      return;
    }
    setTimeout(() => {
      void mcpSignInStatus(workspaceId, c.itemId).then((s) => {
        if (s.status === "done")
          setState("Signed in. The agents get its tools.");
        else if (s.status === "error") {
          setState(null);
          setError(s.error ?? "The sign-in did not finish.");
        } else poll(tries - 1);
      });
    }, 2000);
  }

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-sm font-medium">Sign in (OAuth)</span>
      <div className="flex flex-wrap items-center gap-3">
        <Button
          disabled={busy}
          onClick={() => {
            setError(null);
            // Open the tab now (a click), fill it when the page address is ready.
            const tab = window.open("about:blank", "_blank");
            start(async () => {
              setState("Opening the sign-in page…");
              const s = await startMcpSignIn(workspaceId, c.itemId);
              if (s.url) {
                if (tab) tab.location.href = s.url;
                else window.open(s.url, "_blank");
                setState("Allow access in the new tab, then come back here.");
                poll(300);
              } else {
                tab?.close();
                setState(null);
                setError(s.error ?? "The server gave no sign-in page.");
              }
            });
          }}
        >
          {signedIn ? "Sign in again" : "Sign in"}
        </Button>
        {signedIn && (
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() => {
              start(async () => {
                const r = await mcpSignOut(workspaceId, c.itemId);
                if (r.error) setError(r.error);
                else setState("Signed out.");
              });
            }}
          >
            Sign out
          </Button>
        )}
        <span className="text-sm text-ink-2">
          {state ??
            (signedIn ? "✓ Signed in for this workspace." : "Not signed in.")}
        </span>
      </div>
      {error && <span className="text-sm text-danger">{error}</span>}
      <span className="text-xs text-ink-3">
        Only this workspace uses this sign-in. Servers that don&apos;t offer a
        sign-in take a key below.
      </span>
    </div>
  );
}
