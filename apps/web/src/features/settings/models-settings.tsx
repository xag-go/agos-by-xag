"use client";

import { useState, useTransition } from "react";
import type { ProviderConnection } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { Field, Input } from "@/shared/ui/field";
import { formatWhen } from "@/shared/format";
import { useAsk } from "@/shared/ui/confirm";
import { FormStatus } from "@/shared/ui/form-status";
import { removeApiKey, saveApiKey, testApiKey } from "./provider-login-actions";
import { SubscriptionLogin, WorkspaceLogins } from "./provider-login-steps";
import { Panel } from "@/shared/ui/panel";

export function ModelsSettings({
  providers,
}: {
  providers: ProviderConnection[] | null;
}) {
  if (providers === null) {
    return (
      <Panel as="p" className="px-5 py-4 text-sm text-ink-2">
        Hermes isn&apos;t answering, so connected providers can&apos;t be shown
        right now. Check that Hermes is installed on this machine, then reload.
      </Panel>
    );
  }
  const connectedNow = (p: ProviderConnection) =>
    p.cli.account !== null || p.api !== null;
  const main = providers.filter((p) => !p.more || connectedNow(p));
  const more = providers.filter((p) => p.more && !connectedNow(p));
  return (
    <div className="flex flex-col gap-8">
      <ul className="flex flex-col gap-4">
        {main.map((p) => (
          <ProviderCard key={p.id} provider={p} />
        ))}
      </ul>
      {more.length > 0 && <MoreProviders providers={more} />}
    </div>
  );
}

/** Every other provider Hermes has (its own list): pick one to connect it. */
function MoreProviders({ providers }: { providers: ProviderConnection[] }) {
  const [find, setFind] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const shown = providers.filter((p) =>
    p.name.toLowerCase().includes(find.trim().toLowerCase()),
  );
  const chosen = providers.find((p) => p.id === open);
  return (
    <section className="flex flex-col gap-3">
      <div>
        <h2 className="font-display text-lg font-semibold">
          More providers from Hermes
        </h2>
        <p className="text-sm text-ink-2">
          {providers.length} more that Hermes can use. Connect one and its
          models show up in every model picker.
        </p>
      </div>
      <Input
        placeholder="Find a provider"
        value={find}
        onChange={(e) => {
          setFind(e.target.value);
        }}
        className="max-w-sm"
      />
      {chosen ? (
        <div className="flex flex-col gap-2">
          <button
            type="button"
            className="self-start text-sm text-ink-2 hover:text-ink"
            onClick={() => {
              setOpen(null);
            }}
          >
            ← All providers
          </button>
          <ul>
            <ProviderCard provider={chosen} />
          </ul>
        </div>
      ) : (
        <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {shown.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                className="flex w-full items-center justify-between rounded-xl border border-line bg-panel px-4 py-3 text-left text-sm hover:bg-sunken"
                onClick={() => {
                  setOpen(p.id);
                }}
              >
                <span className="font-medium">{p.name}</span>
                <span className="text-xs text-ink-3">
                  {p.cli.installed ? "Sign in" : "API key"}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ProviderCard({ provider }: { provider: ProviderConnection }) {
  const connected = provider.cli.account !== null || provider.api !== null;

  return (
    <Panel as="li">
      <header className="flex items-center gap-3 border-b border-line px-5 py-3">
        <h2 className="font-display text-lg font-semibold">{provider.name}</h2>
        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-xs font-medium",
            connected ? "bg-sunken text-ink" : "bg-sunken text-ink-3",
          )}
        >
          <span
            aria-hidden="true"
            className={cn(
              "size-1.5 rounded-full",
              connected ? "bg-live" : "bg-ink-3",
            )}
          />
          {connected ? "Connected" : "Not connected"}
        </span>
      </header>

      <div className="grid md:grid-cols-2">
        <section className="flex flex-col gap-3 border-b border-line p-5 md:border-r md:border-b-0">
          <h3 className="text-sm font-semibold">Subscription</h3>
          {provider.cli.installed && !provider.perWorkspace && (
            <p className="text-sm text-ink-2">
              Uses your own {provider.name} account through {provider.cli.tool}.
              Log in once; every workspace uses it.
            </p>
          )}
          {!provider.cli.installed ? (
            <p className="text-sm text-ink-3">
              {provider.cli.tool} has no subscription login for {provider.name}.
              Use an API key.
            </p>
          ) : provider.perWorkspace ? (
            <WorkspaceLogins provider={provider} />
          ) : (
            <SubscriptionLogin provider={provider} />
          )}
        </section>

        <section className="flex flex-col gap-3 p-5">
          <h3 className="text-sm font-semibold">API key</h3>
          {provider.apiKey ? (
            <ApiKeyBox provider={provider} />
          ) : (
            <p className="text-sm text-ink-3">
              {provider.name} has no API key here. Use the subscription.
            </p>
          )}
        </section>
      </div>
    </Panel>
  );
}

/** Paste, test and save an API key; Test again or Remove once saved. */
function ApiKeyBox({ provider }: { provider: ProviderConnection }) {
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, start] = useTransition();
  const { dialog, confirm } = useAsk();
  const api = provider.api;

  return (
    <>
      {dialog}
      <p className="text-sm text-ink-2">
        Saved in Hermes on this server for every workspace. It is never shown
        again or sent to the browser.
      </p>
      {api ? (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="font-medium tabular-nums">
            {api.last4 ? `••••${api.last4}` : "Saved in Hermes"}
          </span>
          {api.status && (
            <span
              className={api.status === "ok" ? "text-ink-3" : "text-danger"}
              title={api.problem || undefined}
            >
              {api.status === "ok"
                ? "works in Hermes"
                : `Hermes: ${api.status}`}
              {api.statusAt ? ` ${formatWhen(api.statusAt)}` : ""}
            </span>
          )}
          <span className="ml-auto flex gap-1">
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => {
                setError(null);
                setNote(null);
                start(async () => {
                  const r = await testApiKey(provider.id);
                  if (r.error) setError(r.error);
                  else setNote(r.message ?? null);
                });
              }}
            >
              {busy ? "Testing…" : "Test"}
            </Button>
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => {
                void (async () => {
                  if (
                    !(await confirm({
                      title: `Remove the ${provider.name} key?`,
                      body: "Workspaces that run on this key stop answering until you add one again.",
                      confirmLabel: "Remove",
                      danger: true,
                    }))
                  )
                    return;
                  setError(null);
                  setNote(null);
                  start(async () => {
                    const r = await removeApiKey(provider.id);
                    if (r.error) setError(r.error);
                  });
                })();
              }}
            >
              Remove
            </Button>
          </span>
        </div>
      ) : (
        <form
          className="flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setError(null);
            setNote(null);
            start(async () => {
              const r = await saveApiKey(provider.id, key);
              if (r.error) setError(r.error);
              else {
                setKey("");
                setNote(r.message ?? null);
              }
            });
          }}
        >
          <Field label="Key" className="flex-1">
            <Input
              type="password"
              autoComplete="off"
              spellCheck={false}
              placeholder="Paste your API key"
              value={key}
              onChange={(e) => {
                setKey(e.target.value);
              }}
              required
            />
          </Field>
          <Button type="submit" disabled={busy || !key.trim()}>
            {busy ? "Testing…" : "Test and save"}
          </Button>
        </form>
      )}
      {note && <p className="text-sm text-ink-2">{note}</p>}
      <FormStatus error={error} />
    </>
  );
}
