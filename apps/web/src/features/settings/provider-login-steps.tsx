"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, useTransition } from "react";
import type { ProviderConnection, ProviderLogin } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { Field, Input } from "@/shared/ui/field";
import { useAsk } from "@/shared/ui/confirm";
import { FormStatus } from "@/shared/ui/form-status";
import {
  cancelProviderLogin,
  logoutProvider,
  sendProviderLoginCode,
  startProviderLogin,
} from "./provider-login-actions";
import { providerLoginStatus } from "./provider-login-status";

const LIVE: ProviderLogin["status"][] = ["starting", "waiting", "checking"];

/** One login (General Settings' Hermes, or one workspace's), done by Hermes. */
function useLogin(provider: string, workspace?: string) {
  const [login, setLogin] = useState<ProviderLogin | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  const router = useRouter();
  const live = login !== null && LIVE.includes(login.status);

  // While a login waits on the provider's page, follow it until it ends.
  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => {
      void (async () => {
        const r = await providerLoginStatus(provider, workspace);
        if (r.error) setError(r.error);
        else if (r.login) {
          setLogin(r.login);
          if (r.login.status === "done") router.refresh();
        }
      })();
    }, 3000);
    return () => {
      window.clearInterval(timer);
    };
  }, [live, provider, workspace, router]);

  const connect = useCallback(() => {
    setError(null);
    start(async () => {
      const r = await startProviderLogin(provider, workspace);
      if (r.error) setError(r.error);
      else if (r.login) {
        setLogin(r.login);
        if (r.login.status === "failed") setError(r.login.message);
      }
    });
  }, [provider, workspace]);
  const sendCode = (code: string) => {
    setError(null);
    start(async () => {
      const r = await sendProviderLoginCode(provider, code, workspace);
      if (r.error) setError(r.error);
      else if (r.login) {
        setLogin(r.login);
        if (r.login.status === "failed") setError(r.login.message);
      }
    });
  };
  const cancel = () => {
    start(async () => {
      await cancelProviderLogin(provider, workspace);
      setLogin((l) => (l ? { ...l, status: "cancelled" } : l));
    });
  };
  const logout = () => {
    setError(null);
    start(async () => {
      const r = await logoutProvider(provider, workspace);
      if (r.error) setError(r.error);
      setLogin(null);
    });
  };
  return { login, error, busy, live, connect, sendCode, cancel, logout };
}

type Login = ReturnType<typeof useLogin>;

/** Connect / Log out for a subscription, done by Hermes on this server. */
export function SubscriptionLogin({
  provider,
}: {
  provider: ProviderConnection;
}) {
  const flow = useLogin(provider.id);
  const { dialog, confirm } = useAsk();

  if (provider.cli.account && !flow.live) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        {dialog}
        <p className="text-sm">
          Connected with{" "}
          <span className="font-medium">{provider.cli.account}</span>
        </p>
        <Button
          variant="ghost"
          className="ml-auto"
          disabled={flow.busy}
          onClick={() => {
            void (async () => {
              if (
                !(await confirm({
                  title: `Log out of ${provider.name}?`,
                  body: `Every workspace that uses a ${provider.name} model stops answering until you connect again.`,
                  confirmLabel: "Log out",
                  danger: true,
                }))
              )
                return;
              flow.logout();
            })();
          }}
        >
          {flow.busy ? "Logging out…" : "Log out"}
        </Button>
        <FormStatus error={flow.error} className="w-full" />
      </div>
    );
  }

  if (!flow.live) {
    return (
      <div className="flex flex-col gap-2">
        <Button
          className="self-start"
          disabled={flow.busy}
          onClick={flow.connect}
        >
          {flow.busy ? "Starting…" : "Connect subscription"}
        </Button>
        {flow.login?.status === "done" && (
          <p className="text-sm text-ink-2">Connected. Updating this card…</p>
        )}
        <FormStatus
          error={
            flow.error ??
            (flow.login?.status === "failed" ? flow.login.message : null)
          }
        />
      </div>
    );
  }
  return <LoginSteps name={provider.name} flow={flow} />;
}

type WorkspaceState = { id: string; name: string; connected: boolean };

/** Each workspace signs in with its own Hermes: the list, and Connect all. */
export function WorkspaceLogins({
  provider,
}: {
  provider: ProviderConnection;
}) {
  const rows = provider.workspaces ?? [];
  const [queue, setQueue] = useState<string[]>([]);
  const missing = rows.filter((w) => !w.connected);
  const active = queue[0] ?? null;
  const next = useCallback((id: string) => {
    setQueue((q) => q.filter((x) => x !== id));
  }, []);

  if (rows.length === 0) {
    return (
      <p className="text-sm text-ink-3">
        No workspace yet. Each workspace connects its own {provider.name}{" "}
        account here once it exists.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-ink-2">
        Each workspace signs in on its own: one {provider.name} login per
        workspace. Use the same account for all of them.
      </p>
      <ul className="flex flex-col divide-y divide-line rounded-lg border border-line">
        {rows.map((w) => (
          <WorkspaceLoginRow
            key={w.id}
            provider={provider}
            workspace={w}
            turn={active === w.id}
            onEnd={next}
          />
        ))}
      </ul>
      {missing.length > 1 && queue.length === 0 && (
        <Button
          className="self-start"
          onClick={() => {
            setQueue(missing.map((w) => w.id));
          }}
        >
          Connect all {missing.length} workspaces
        </Button>
      )}
      {queue.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 text-sm text-ink-2">
          <span>
            Connecting {rows.find((w) => w.id === active)?.name}
            {queue.length > 1 ? `, then ${queue.length - 1} more` : ""}.
          </span>
          {queue.length > 1 && (
            <Button
              variant="ghost"
              onClick={() => {
                setQueue(active ? [active] : []);
              }}
            >
              Stop after this one
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

function WorkspaceLoginRow({
  provider,
  workspace,
  turn,
  onEnd,
}: {
  provider: ProviderConnection;
  workspace: WorkspaceState;
  turn: boolean;
  onEnd: (id: string) => void;
}) {
  const flow = useLogin(provider.id, workspace.id);
  const { dialog, confirm } = useAsk();
  const started = useRef(false);
  const status = flow.login?.status;
  const { connect, live, busy, error } = flow;

  // "Connect all": this row's turn starts its login by itself…
  useEffect(() => {
    if (!turn || started.current) return;
    if (workspace.connected) {
      onEnd(workspace.id);
      return;
    }
    started.current = true;
    connect();
  }, [turn, workspace.connected, workspace.id, connect, onEnd]);
  // …and hands over to the next one once it is connected (or given up).
  useEffect(() => {
    if (!turn || !started.current || live || busy) return;
    if (status === "done" || status === "cancelled" || status === "failed")
      onEnd(workspace.id);
    else if (error) onEnd(workspace.id);
  }, [turn, live, busy, status, error, workspace.id, onEnd]);

  const connected = workspace.connected || status === "done";
  return (
    <li className="flex flex-col gap-2 px-3 py-2">
      {dialog}
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span
          aria-hidden="true"
          className={cn(
            "size-1.5 rounded-full",
            connected ? "bg-live" : "bg-ink-3",
          )}
        />
        <span className="font-medium">{workspace.name}</span>
        <span className="text-ink-3">
          {connected ? "Connected" : "Not connected"}
        </span>
        {!live && (
          <span className="ml-auto">
            {connected ? (
              <Button
                variant="ghost"
                className="h-7"
                disabled={busy}
                onClick={() => {
                  void (async () => {
                    if (
                      !(await confirm({
                        title: `Log ${workspace.name} out of ${provider.name}?`,
                        body: `${workspace.name} stops answering with ${provider.name} models until you connect it again. Other workspaces keep their own login.`,
                        confirmLabel: "Log out",
                        danger: true,
                      }))
                    )
                      return;
                    flow.logout();
                  })();
                }}
              >
                {busy ? "Logging out…" : "Log out"}
              </Button>
            ) : (
              <Button className="h-7" disabled={busy} onClick={connect}>
                {busy ? "Starting…" : "Connect"}
              </Button>
            )}
          </span>
        )}
      </div>
      {live && <LoginSteps name={provider.name} flow={flow} />}
      {!live && (
        <FormStatus
          error={
            error ??
            (status === "failed" ? (flow.login?.message ?? null) : null)
          }
        />
      )}
    </li>
  );
}

/** The provider's page to open, the code to enter or paste, and Cancel. */
function LoginSteps({ name, flow }: { name: string; flow: Login }) {
  const [code, setCode] = useState("");
  const login = flow.login;
  if (login === null) return null;
  return (
    <div className="flex flex-col gap-3 rounded-lg bg-sunken p-3 text-sm">
      {login.url ? (
        <>
          <p className="text-ink-2">
            1. Open the {name} page and sign in with your account.
          </p>
          <a
            href={login.url}
            target="_blank"
            rel="noreferrer noopener"
            className="self-start rounded-md bg-panel px-3 py-1.5 font-medium underline-offset-2 hover:underline"
          >
            Open {name} sign-in ↗
          </a>
          {login.userCode && (
            <div>
              <p className="text-ink-2">2. Enter this code there:</p>
              <p className="mt-1 flex items-center gap-2">
                <span className="rounded-md bg-panel px-2 py-1 font-mono text-base font-semibold tracking-wider">
                  {login.userCode}
                </span>
                <Button
                  variant="ghost"
                  className="h-7"
                  onClick={() => {
                    void navigator.clipboard.writeText(login.userCode ?? "");
                  }}
                >
                  Copy
                </Button>
              </p>
            </div>
          )}
          {login.needsCode && (
            <form
              className="flex items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                flow.sendCode(code);
              }}
            >
              <Field
                label="2. Paste the code the page shows after Allow"
                className="flex-1"
              >
                <Input
                  value={code}
                  onChange={(e) => {
                    setCode(e.target.value);
                  }}
                  autoComplete="off"
                  spellCheck={false}
                  required
                />
              </Field>
              <Button type="submit" disabled={flow.busy || !code.trim()}>
                {flow.busy ? "Checking…" : "Finish"}
              </Button>
            </form>
          )}
        </>
      ) : null}
      <p className="text-ink-3">
        {login.status === "checking"
          ? "Checking the login…"
          : login.message || "Starting…"}
      </p>
      <FormStatus error={flow.error} />
      <Button variant="ghost" className="self-start" onClick={flow.cancel}>
        Cancel
      </Button>
    </div>
  );
}
