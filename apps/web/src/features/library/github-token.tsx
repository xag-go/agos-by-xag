"use client";

import { useEffect, useState, useTransition } from "react";
import type { GithubTokenState } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { Field, Input } from "@/shared/ui/field";
import { useAsk } from "@/shared/ui/confirm";
import { FormStatus } from "@/shared/ui/form-status";
import {
  githubTokenStatus,
  removeGithubToken,
  saveGithubToken,
} from "./actions";
import { PanelSection } from "@/shared/ui/panel";

const NEW_TOKEN_URL = "https://github.com/settings/personal-access-tokens/new";

function resetTime(reset: number | null | undefined): string | null {
  if (!reset) return null;
  return new Date(reset * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** What Hermes's Skills Hub uses to read GitHub, in plain words. */
function usage(state: GithubTokenState): string {
  const who =
    state.method === "pat"
      ? "Skill installs read GitHub with your token"
      : state.method === "anonymous"
        ? "Skill installs read GitHub without a token"
        : `Skill installs read GitHub with this server's ${state.method === "gh-cli" ? "GitHub CLI login" : "GitHub App"}`;
  if (typeof state.limit !== "number" || typeof state.remaining !== "number")
    return state.error ? `${who}. GitHub didn't answer just now.` : `${who}.`;
  const back = resetTime(state.reset);
  const left = `${state.remaining.toLocaleString()} of ${state.limit.toLocaleString()} requests left this hour`;
  return state.remaining === 0 && back
    ? `${who}: none left this hour (back at ${back}).`
    : `${who}: ${left}.`;
}

export function GithubTokenCard() {
  const [state, setState] = useState<GithubTokenState | null>(null);
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, start] = useTransition();
  const { dialog, confirm } = useAsk();

  useEffect(() => {
    let live = true;
    void githubTokenStatus().then((r) => {
      if (!live) return;
      setState(r.state);
      if (r.error) setError(r.error);
      setLoading(false);
    });
    return () => {
      live = false;
    };
  }, []);

  return (
    <PanelSection className="flex max-w-3xl flex-col gap-3 p-5">
      {dialog}
      <div className="flex flex-col gap-1">
        <h2 className="font-medium">GitHub token (for installing skills)</h2>
        <p className="text-sm text-ink-2">
          Skills are downloaded from GitHub. Without a token GitHub allows this
          server 60 requests an hour, and a few installs use them up. A token
          raises it to 5,000. Make a{" "}
          <a
            href={NEW_TOKEN_URL}
            target="_blank"
            rel="noreferrer"
            className="underline"
          >
            fine-grained token
          </a>{" "}
          with “Public repositories (read-only)” and no permissions. It is kept
          for installing skills only; workspaces never get it.
        </p>
      </div>
      {loading ? (
        <p className="text-sm text-ink-3">Checking…</p>
      ) : state ? (
        <p className="text-sm">{usage(state)}</p>
      ) : null}
      {state?.saved ? (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="font-medium">Token saved</span>
          <span className="ml-auto">
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => {
                void (async () => {
                  if (
                    !(await confirm({
                      title: "Remove the GitHub token?",
                      body: "Skill installs go back to 60 GitHub requests an hour.",
                      confirmLabel: "Remove",
                      danger: true,
                    }))
                  )
                    return;
                  setError(null);
                  setNote(null);
                  start(async () => {
                    const r = await removeGithubToken();
                    if (r.error) setError(r.error);
                    else {
                      setState(r.state);
                      setNote("Removed.");
                    }
                  });
                })();
              }}
            >
              Remove
            </Button>
          </span>
        </div>
      ) : (
        !loading && (
          <form
            className="flex items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              setError(null);
              setNote(null);
              start(async () => {
                const r = await saveGithubToken(token);
                if (r.error) setError(r.error);
                else {
                  setToken("");
                  setState(r.state);
                  setNote("Saved. GitHub took the token.");
                }
              });
            }}
          >
            <Field label="Token" className="flex-1">
              <Input
                type="password"
                autoComplete="off"
                spellCheck={false}
                placeholder="github_pat_…"
                value={token}
                onChange={(e) => {
                  setToken(e.target.value);
                }}
                required
              />
            </Field>
            <Button type="submit" disabled={busy || !token.trim()}>
              {busy ? "Checking…" : "Check and save"}
            </Button>
          </form>
        )
      )}
      {note && <p className="text-sm text-ink-2">{note}</p>}
      <FormStatus error={error} />
    </PanelSection>
  );
}
