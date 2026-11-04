"use client";

import { useEffect, useState, useTransition } from "react";
import type {
  ComposioAccount,
  ComposioAuthSetup,
  ComposioToolkit,
} from "@/data/types";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import {
  composioAccounts,
  composioAuthSetup,
  composioSetUp,
  removeComposioAccount,
  setWorkspaceComposioKey,
} from "./actions";

export const COMPOSIO = "composio";

/** This workspace's own Composio project key (plan: one Composio project per
 * workspace, so its key reaches only this workspace's accounts). Checked with
 * Composio, refused if another workspace uses that project; never shown again. */
export function ComposioKey({
  workspaceId,
  replace = false,
}: {
  workspaceId: string;
  replace?: boolean;
}) {
  const [value, setValue] = useState("");
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  return (
    <span className="mt-2 flex flex-col gap-2">
      {!editing && (
        <button
          type="button"
          className="self-start text-sm text-ink underline decoration-line-strong underline-offset-2 hover:decoration-ink"
          onClick={() => {
            setEditing(true);
          }}
        >
          {replace ? "Replace this workspace's key" : "Use a project key"}
        </button>
      )}
      {editing && (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setError(null);
            start(async () => {
              const r = await setWorkspaceComposioKey(workspaceId, value);
              if (r.error) {
                setError(r.error);
                return;
              }
              setValue("");
              setEditing(false);
            });
          }}
        >
          <Input
            type="password"
            autoComplete="off"
            placeholder="ak_…"
            aria-label="This workspace's Composio project key"
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
            }}
            className="h-8 max-w-60"
          />
          <Button
            type="submit"
            className="h-8"
            variant="secondary"
            disabled={busy || !value.trim()}
          >
            {busy ? "Checking…" : "Save key"}
          </Button>
          <Button
            type="button"
            className="h-8"
            variant="ghost"
            onClick={() => {
              setEditing(false);
              setValue("");
              setError(null);
            }}
          >
            Cancel
          </Button>
          <span className="w-full text-xs text-ink-3">
            In Composio, make one project for this workspace, then its Settings
            → API Keys (starts with ak_). Each workspace has its own project.
          </span>
        </form>
      )}
      <FormStatus error={error} />
    </span>
  );
}

/** The apps connected in this workspace's own Composio project (add more with
 * the search below). */
export function ComposioApps({ workspaceId }: { workspaceId: string }) {
  const [accounts, setAccounts] = useState<ComposioAccount[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  const [round, setRound] = useState(0);
  useEffect(() => {
    let live = true;
    void composioAccounts(workspaceId, round > 0).then((r) => {
      if (!live) return;
      setAccounts(r.accounts);
      setError(r.error);
    });
    return () => {
      live = false;
    };
  }, [workspaceId, round]);
  return (
    <div className="mt-3 flex flex-col gap-2 rounded-xl bg-sunken px-4 py-3">
      <span className="flex items-center gap-3 text-sm font-medium">
        Its apps
        <button
          type="button"
          className="text-sm font-normal text-ink-2 hover:text-ink"
          onClick={() => {
            setRound((n) => n + 1);
          }}
        >
          Refresh
        </button>
      </span>
      {accounts === null ? (
        <span className="text-sm text-ink-3">Reading Composio…</span>
      ) : accounts.length === 0 ? (
        <span className="text-sm text-ink-3">
          None yet: search one below and Connect it.
        </span>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {accounts.map((acc) => (
            <li
              key={acc.id}
              className="flex flex-wrap items-center gap-3 text-sm"
            >
              <Logo
                toolkit={undefined}
                name={acc.toolkit}
                src={`https://logos.composio.dev/api/${acc.toolkit}`}
              />
              <span className="font-medium capitalize">
                {acc.toolkit.replace(/[_-]/g, " ")}
              </span>
              <span className="text-ink-3">
                {acc.label ? `${acc.label} · ` : ""}
                {acc.status === "ACTIVE"
                  ? "connected"
                  : acc.status.toLowerCase()}
                {acc.forAgent
                  ? ""
                  : " · not for this agent (connected in Composio): Remove it, then Connect it here"}
              </span>
              <button
                type="button"
                className="text-danger hover:underline"
                disabled={busy}
                onClick={() => {
                  setError(null);
                  start(async () => {
                    const r = await removeComposioAccount(workspaceId, acc.id);
                    if (r.error) setError(r.error);
                    setRound((n) => n + 1);
                  });
                }}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
      <FormStatus error={error} />
    </div>
  );
}

/** One app's developer app (client ID and secret…), saved into this workspace's
 * Composio project: then Connect works for it. */
export function AppSetup({
  workspaceId,
  slug,
  toolkit,
  onClose,
  onDone,
}: {
  workspaceId: string;
  slug: string;
  toolkit: ComposioToolkit | undefined;
  onClose: () => void;
  onDone: () => void;
}) {
  const [form, setForm] = useState<ComposioAuthSetup | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  useEffect(() => {
    let live = true;
    void composioAuthSetup(workspaceId, slug).then((r) => {
      if (!live) return;
      setForm(r.setup);
      setError(r.error);
    });
    return () => {
      live = false;
    };
  }, [workspaceId, slug]);
  const name = toolkit?.name ?? slug;
  return (
    <form
      className="flex flex-col gap-2.5 rounded-lg border border-line bg-panel px-4 py-3"
      onSubmit={(e) => {
        e.preventDefault();
        setError(null);
        start(async () => {
          const r = await composioSetUp(workspaceId, slug, values);
          if (r.error) setError(r.error);
          else onDone();
        });
      }}
    >
      <span className="flex items-center gap-2.5 text-sm font-medium">
        <Logo toolkit={toolkit} name={name} />
        Set up {name} for this workspace
      </span>
      <span className="text-xs text-ink-3">
        Make an app in {name}&apos;s developer site, then paste its details
        here. They go to this workspace&apos;s Composio project only.
      </span>
      {form === null ? (
        error ? null : (
          <span className="text-sm text-ink-3">Reading Composio…</span>
        )
      ) : (
        <>
          {form.redirectUri ? (
            <span className="text-xs text-ink-2">
              In that app, allow this redirect URL:{" "}
              <code className="break-all select-all">{form.redirectUri}</code>
            </span>
          ) : null}
          {form.fields.map((f) => (
            <label key={f.name} className="flex flex-col gap-1 text-sm">
              {f.label}
              <Input
                type={f.secret ? "password" : "text"}
                autoComplete="off"
                className="h-8 max-w-96"
                value={values[f.name] ?? ""}
                onChange={(e) => {
                  const v = e.target.value;
                  setValues((old) => ({ ...old, [f.name]: v }));
                }}
              />
              {f.description ? (
                <span className="text-xs text-ink-3">{f.description}</span>
              ) : null}
            </label>
          ))}
        </>
      )}
      <span className="flex gap-2">
        <Button type="submit" disabled={busy || form === null}>
          Save
        </Button>
        <Button type="button" variant="secondary" onClick={onClose}>
          Cancel
        </Button>
      </span>
      <FormStatus error={error} />
    </form>
  );
}

export function Logo({
  toolkit,
  name,
  src,
}: {
  toolkit: ComposioToolkit | undefined;
  name: string;
  src?: string;
}) {
  const logo = toolkit?.logo ?? src;
  if (!logo)
    return (
      <span
        aria-hidden
        className="grid size-7 shrink-0 place-items-center rounded-md bg-sunken text-xs font-semibold"
      >
        {name.slice(0, 1).toUpperCase()}
      </span>
    );
  return (
    // eslint-disable-next-line @next/next/no-img-element -- Composio's logo CDN
    <img
      src={logo}
      alt=""
      width={28}
      height={28}
      loading="lazy"
      referrerPolicy="no-referrer"
      className="size-7 shrink-0 rounded-md bg-white object-contain p-0.5"
    />
  );
}
