"use client";

import { useState, useTransition } from "react";
import type { LibraryItem } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { Field, Input, Select } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { SignIn } from "@/features/settings/sign-in";
import { setToolService } from "./actions";

type Service = {
  name: string;
  badge: string;
  about: string;
  nous: boolean;
  login?: string;
  /** The sign-in it needs, as the core maps Hermes's service (null: none;
   * `id` null: one AGOS can't start). */
  signIn?: { id: string | null; label: string } | null;
  env: { key: string; prompt: string; url: string }[];
};

/** A tool that uses an outside service: Hermes's list of services, set up here
 * once (Hermes keeps the key; AGOS shows only its end). */
export function ToolService({ item }: { item: LibraryItem }) {
  const services = item.services as Service[];
  const current = item.service as {
    provider: string;
    keys: Record<string, string>;
  } | null;
  const [open, setOpen] = useState(false);
  const [pick, setPick] = useState(
    current?.provider ?? services[0]?.name ?? "",
  );
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [busy, start] = useTransition();
  if (services.length === 0) return null;
  const chosen = services.find((s) => s.name === pick);
  const signIn = chosen?.signIn ?? null;
  return (
    <div className="mt-2 text-sm">
      <p className="text-ink-3">
        {current
          ? `Service: ${current.provider}${Object.values(current.keys).length ? ` (key ••••${Object.values(current.keys).join(", ••••")})` : ""}`
          : "No service set up yet."}{" "}
        <button
          type="button"
          className="text-ink-2 underline-offset-2 hover:text-ink hover:underline"
          onClick={() => {
            setOpen((o) => !o);
          }}
        >
          {open ? "Close" : current ? "Change" : "Set up"}
        </button>
      </p>
      {open && (
        <form
          className="mt-3 flex max-w-xl flex-col gap-3 rounded-xl border border-line p-4"
          onSubmit={(e) => {
            e.preventDefault();
            setError(null);
            setDone(null);
            start(async () => {
              const r = await setToolService(item.name, pick, keys);
              if (r.error) setError(r.error);
              else {
                setKeys({});
                setDone(
                  r.problems?.length
                    ? `Saved. Not every workspace took it: ${r.problems.join("; ")}`
                    : r.installing
                      ? "Saved for every workspace. It is installing what it needs (a few minutes)."
                      : "Saved for every workspace.",
                );
              }
            });
          }}
        >
          <Field label="Service" hint={chosen?.about}>
            <Select
              value={pick}
              onChange={(e) => {
                setPick(e.target.value);
                setKeys({});
              }}
            >
              {services.map((s) => (
                <option key={s.name} value={s.name}>
                  {s.name}
                  {s.badge ? ` (${s.badge})` : ""}
                </option>
              ))}
            </Select>
          </Field>
          {chosen?.env.map((e) => (
            <Field
              key={e.key}
              label={e.prompt || e.key}
              hint={
                current?.provider === pick && current.keys[e.key]
                  ? `Saved: ••••${current.keys[e.key]}. Leave empty to keep it.`
                  : undefined
              }
            >
              <Input
                type="password"
                autoComplete="off"
                value={keys[e.key] ?? ""}
                onChange={(ev) => {
                  setKeys({ ...keys, [e.key]: ev.target.value });
                }}
              />
              {e.url && (
                <a
                  href={e.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs text-ink-2 underline"
                >
                  Get a key
                </a>
              )}
            </Field>
          ))}
          {signIn?.id ? (
            <SignIn login={{ id: signIn.id, label: signIn.label }} />
          ) : signIn ? (
            <p className="text-xs text-ink-2">{signIn.label}</p>
          ) : null}
          {chosen && chosen.env.length === 0 && !chosen.login && (
            <p className="text-xs text-ink-3">
              No key needed (it uses a login this server already has, or runs on
              this machine).
            </p>
          )}
          <Button
            type="submit"
            variant="primary"
            className="self-start"
            disabled={busy}
          >
            {busy ? "Saving…" : "Save for every workspace"}
          </Button>
          <FormStatus error={error} />
          {done && <p className="text-xs text-success">{done}</p>}
        </form>
      )}
    </div>
  );
}
