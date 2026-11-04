"use client";

import { useState, useSyncExternalStore, useTransition } from "react";
import type { McpToken } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { FormStatus } from "@/shared/ui/form-status";
import { makeMcpToken, removeMcpToken } from "./actions";
import { PanelSection } from "@/shared/ui/panel";

const noChange = () => () => undefined;

function Snippet({ title, text }: { title: string; text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="overflow-hidden rounded-xl border border-line bg-sunken">
      <div className="flex items-center justify-between border-b border-line px-3 py-1 text-xs text-ink-3">
        <span>{title}</span>
        <button
          type="button"
          className="rounded px-1.5 py-0.5 hover:bg-panel hover:text-ink"
          onClick={() => {
            void navigator.clipboard.writeText(text).then(() => {
              setCopied(true);
              setTimeout(() => {
                setCopied(false);
              }, 1500);
            });
          }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto px-3 py-2.5 font-mono text-caption leading-relaxed whitespace-pre">
        {text}
      </pre>
    </div>
  );
}

/** Settings → Connections → MCP: the workspace's tools for Claude Desktop,
 * Claude Code or Codex, at AGOS's own address (Tailscale only), with this
 * workspace's token (it opens this workspace and no other). */
export function McpCard({
  workspaceId,
  name,
  token,
}: {
  workspaceId: string;
  name: string;
  token: McpToken;
}) {
  // AGOS's own address as his browser reaches it (Tailscale's name).
  const origin = useSyncExternalStore(
    noChange,
    () => window.location.origin,
    () => "",
  );
  const [shown, setShown] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  const url = `${origin}/api/mcp/${workspaceId}`;
  const key = `agos-${
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "") || workspaceId
  }`;
  const secret = token.token ?? "";
  const masked = shown ? secret : `${secret.slice(0, 12)}…`;
  return (
    <PanelSection className="flex flex-col gap-3 p-5">
      <h2 className="font-display text-base font-semibold">
        Outside assistants (MCP)
      </h2>
      <p className="text-sm text-ink-2">
        Your Claude Desktop, Claude Code or Codex can work in this workspace:
        list, create, comment and complete its cards, read its goals, answer its
        Inbox and search it. It reaches AGOS the way you do (Tailscale, never
        public), with this workspace&apos;s token only.
      </p>
      <p className="text-xs text-ink-3">Tools: {token.tools.join(", ")}</p>
      {token.token ? (
        <>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-ink-3">Token</span>
            <code className="rounded bg-sunken px-1.5 py-0.5 font-mono text-xs">
              {masked}
            </code>
            <Button
              variant="ghost"
              onClick={() => {
                setShown((s) => !s);
              }}
            >
              {shown ? "Hide" : "Show"}
            </Button>
            {token.madeAt && (
              <span className="text-xs text-ink-3">
                made {new Date(token.madeAt).toLocaleString()}
              </span>
            )}
          </div>
          <Snippet
            title="Claude Code"
            text={`claude mcp add --transport http ${key} ${url} \\\n  --header "Authorization: Bearer ${secret}"`}
          />
          <Snippet
            title="Claude Desktop (claude_desktop_config.json)"
            text={JSON.stringify(
              {
                mcpServers: {
                  [key]: {
                    command: "npx",
                    args: [
                      "-y",
                      "mcp-remote",
                      url,
                      "--header",
                      `Authorization: Bearer ${secret}`,
                    ],
                  },
                },
              },
              null,
              2,
            )}
          />
          <Snippet
            title="Codex (~/.codex/config.toml, token in AGOS_MCP_TOKEN)"
            text={`[mcp_servers.${key.replace(/-/g, "_")}]\nurl = "${url}"\nbearer_token_env_var = "AGOS_MCP_TOKEN"\n\n# in your shell:\nexport AGOS_MCP_TOKEN=${secret}`}
          />
        </>
      ) : (
        <p className="text-sm text-ink-3">
          No token yet: nothing outside can reach this workspace.
        </p>
      )}
      <div className="flex items-center gap-2">
        <Button
          variant={token.token ? "secondary" : "primary"}
          disabled={busy}
          onClick={() => {
            start(async () => {
              setError((await makeMcpToken(workspaceId)).error);
            });
          }}
        >
          {token.token ? "New token (the old one stops)" : "Make a token"}
        </Button>
        {token.token && (
          <Button
            variant="danger"
            disabled={busy}
            onClick={() => {
              start(async () => {
                setError((await removeMcpToken(workspaceId)).error);
              });
            }}
          >
            Remove
          </Button>
        )}
        <FormStatus error={error} />
      </div>
    </PanelSection>
  );
}
