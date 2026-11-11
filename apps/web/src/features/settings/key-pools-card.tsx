"use client";

import { useState, useTransition } from "react";
import type { KeyPools } from "@/data/queries";
import type { CatalogProvider } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { useAsk } from "@/shared/ui/confirm";
import { Field, Input, Select } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import {
  addPoolKey,
  movePoolKey,
  removePoolKey,
  setPoolStrategy,
} from "./key-pools-actions";
import { PanelSection } from "@/shared/ui/panel";

const STRATEGY: Record<string, string> = {
  fill_first: "Use the first key until it runs out, then the next",
  round_robin: "Take turns",
  least_used: "The least used key",
  random: "Any key at random",
};

type Status = { error: string | null; saved?: boolean };

/** Several keys per provider: Hermes's own credential pool, as Hermes has it.
 * Keys added here are numbered lines of Hermes's managed .env (one place, read by
 * every workspace); how Hermes picks is one line of its managed config. */
export function KeyPoolsCard({
  pools,
  catalog,
}: {
  pools: KeyPools | null;
  catalog: CatalogProvider[];
}) {
  const [status, setStatus] = useState<Status>({ error: null });
  const [busy, start] = useTransition();
  const { dialog, confirm } = useAsk();
  const run = (job: () => Promise<Status>) => {
    start(async () => {
      setStatus(await job());
    });
  };
  const choices = [
    ...new Set([
      ...(pools?.providers.map((p) => p.provider) ?? []),
      ...catalog.flatMap((p) =>
        p.hermesProviders?.api ? [p.hermesProviders.api] : [],
      ),
    ]),
  ].sort();
  const [provider, setProvider] = useState(choices[0] ?? "");
  const [key, setKey] = useState("");
  return (
    <PanelSection
      id="key-pools"
      aria-labelledby="key-pools-title"
      className="flex scroll-mt-6 flex-col gap-4 p-5"
    >
      <div>
        <h3 id="key-pools-title" className="font-medium">
          Several keys per provider
        </h3>
        <p className="mt-1 text-sm text-ink-2">
          When one key is out of credit or rate-limited, the next takes over. A
          key added here is one shared .env line (named after the
          provider&apos;s key, with _2, _3…), so every workspace uses it, new
          ones too; a workspace&apos;s own line of the same name wins there. The
          key itself is never shown again, only a short preview. How one is
          picked among them is the credential_pool_strategies setting, one value
          for every workspace.
        </p>
      </div>
      {pools === null ? (
        <p className="text-sm text-ink-2">
          The engine isn&apos;t answering, so the key pool can&apos;t be shown
          now.
        </p>
      ) : pools.providers.length === 0 ? (
        <p className="text-sm text-ink-2">
          No provider has keys in the pool yet.
        </p>
      ) : (
        <ul className="flex flex-col gap-4">
          {pools.providers.map((p) => (
            <li key={p.provider} className="flex flex-col gap-2">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <span className="text-sm font-medium">{p.provider}</span>
                <Field label="How keys are picked" className="w-80">
                  <Select
                    value={p.strategy}
                    disabled={busy}
                    onChange={(e) => {
                      const next = e.target.value;
                      run(() => setPoolStrategy(p.provider, next));
                    }}
                  >
                    {pools.strategies.map((s) => (
                      <option key={s} value={s}>
                        {STRATEGY[s] ?? s}
                      </option>
                    ))}
                  </Select>
                </Field>
              </div>
              <ol className="flex flex-col gap-1">
                {p.entries.map((e, i) => (
                  <li
                    key={e.label}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-sunken px-3 py-2 text-sm"
                  >
                    <span className="flex flex-col">
                      <span>
                        {i + 1}. {e.label}{" "}
                        <code className="text-xs text-ink-2">{e.preview}</code>
                      </span>
                      <span className="text-xs text-ink-2">
                        {e.source.startsWith("env:")
                          ? "From Settings → Models"
                          : e.source === "manual"
                            ? "Added here"
                            : `From ${e.source}`}
                        {" · "}
                        {e.status ? `Last use: ${e.status}` : "Not used yet"}
                        {e.requests ? ` · ${e.requests} requests` : ""}
                        {e.problem ? ` · ${e.problem}` : ""}
                      </span>
                    </span>
                    <span className="flex gap-2">
                      <Button
                        className="h-8"
                        disabled={
                          busy || !e.movable || !p.entries[i - 1]?.movable
                        }
                        aria-label={`Move ${e.label} up`}
                        onClick={() => {
                          run(() => movePoolKey(p.provider, e.label, i - 1));
                        }}
                      >
                        Up
                      </Button>
                      <Button
                        className="h-8"
                        disabled={
                          busy || !e.movable || !p.entries[i + 1]?.movable
                        }
                        aria-label={`Move ${e.label} down`}
                        onClick={() => {
                          run(() => movePoolKey(p.provider, e.label, i + 1));
                        }}
                      >
                        Down
                      </Button>
                      {e.removable ? (
                        <Button
                          className="h-8"
                          disabled={busy}
                          onClick={() => {
                            void confirm({
                              title: `Remove ${e.label} from ${p.provider}?`,
                              body: "No workspace uses it any more.",
                              confirmLabel: "Remove",
                            }).then((yes) => {
                              if (yes)
                                run(() => removePoolKey(p.provider, e.label));
                            });
                          }}
                        >
                          Remove
                        </Button>
                      ) : null}
                    </span>
                  </li>
                ))}
              </ol>
            </li>
          ))}
        </ul>
      )}
      {pools !== null && (pools.workspaces ?? []).length > 0 ? (
        <details className="border-t border-line pt-4">
          <summary className="cursor-pointer text-sm font-medium">
            Each workspace&apos;s pool, as that workspace has it
          </summary>
          <ul className="mt-3 flex flex-col gap-3">
            {(pools.workspaces ?? []).map((w) => (
              <li key={w.workspaceId} className="flex flex-col gap-1 text-sm">
                <span className="font-medium">{w.name}</span>
                {w.problem ? (
                  <span className="text-xs text-ink-2">{w.problem}</span>
                ) : w.providers.length === 0 ? (
                  <span className="text-xs text-ink-2">
                    No keys in its pool.
                  </span>
                ) : (
                  w.providers.map((p) => (
                    <span key={p.provider} className="text-xs text-ink-2">
                      {p.provider}:{" "}
                      {p.entries
                        .map(
                          (e) =>
                            `${e.label}${e.preview ? ` (${e.preview})` : ""}${e.status ? ` · ${e.status}` : ""}`,
                        )
                        .join(", ")}
                    </span>
                  ))
                )}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {pools !== null ? (
        <div className="grid gap-3 border-t border-line pt-4 sm:grid-cols-2">
          <Field label="Provider">
            <Select
              value={provider}
              onChange={(e) => {
                setProvider(e.target.value);
              }}
            >
              {choices.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="API key">
            <Input
              type="password"
              autoComplete="off"
              value={key}
              onChange={(e) => {
                setKey(e.target.value);
              }}
            />
          </Field>
          <div className="sm:col-span-2">
            <Button
              variant="primary"
              disabled={busy || !provider || !key.trim()}
              onClick={() => {
                start(async () => {
                  const r = await addPoolKey(provider, key);
                  setStatus(r);
                  if (!r.error) setKey("");
                });
              }}
            >
              {busy ? "Saving…" : "Add key"}
            </Button>
          </div>
        </div>
      ) : null}
      <FormStatus error={status.error} saved={status.saved} />
      {dialog}
    </PanelSection>
  );
}
