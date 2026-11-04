"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { Button } from "@/shared/ui/button";
import { FormStatus } from "@/shared/ui/form-status";
import { startProviderLogin } from "./provider-login-actions";
import { providerLoginStatus } from "./provider-login-status";

/** Hermes's own sign-in for a service (the device page and its code); the login
 * is saved in Hermes, where every workspace uses it. */
export function SignIn({ login }: { login: { id: string; label: string } }) {
  const [state, setState] = useState<{
    url?: string | null;
    code?: string | null;
    message?: string;
    status?: string;
  }>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  const router = useRouter();
  const follow = async () => {
    for (let i = 0; i < 180; i++) {
      await new Promise((r) => setTimeout(r, 5000));
      const r = await providerLoginStatus(login.id);
      if (r.error) {
        setError(r.error);
        return;
      }
      const l = r.login;
      if (!l) return;
      setState({
        url: l.url,
        code: l.userCode,
        message: l.message,
        status: l.status,
      });
      if (l.status === "done") router.refresh();
      if (["done", "failed", "cancelled", "idle"].includes(l.status)) return;
    }
  };
  return (
    <div className="flex flex-col gap-2 rounded-lg bg-sunken p-3">
      {state.status === "done" ? (
        <p className="text-xs text-success">
          Signed in. Now save to use it in every workspace.
        </p>
      ) : state.url ? (
        <p className="text-xs text-ink-2">
          Open{" "}
          <a
            href={state.url}
            target="_blank"
            rel="noreferrer"
            className="underline"
          >
            this page
          </a>
          {state.code ? (
            <>
              {" "}
              and enter{" "}
              <span className="font-mono font-semibold">{state.code}</span>
            </>
          ) : null}
          . {state.message}
        </p>
      ) : (
        <Button
          type="button"
          className="self-start"
          disabled={busy}
          onClick={() => {
            setError(null);
            start(async () => {
              const r = await startProviderLogin(login.id);
              if (r.error) setError(r.error);
              else if (r.login) {
                setState({
                  url: r.login.url,
                  code: r.login.userCode,
                  message: r.login.message,
                  status: r.login.status,
                });
                void follow();
              }
            });
          }}
        >
          {busy ? "Starting…" : login.label}
        </Button>
      )}
      <FormStatus error={error} />
    </div>
  );
}
