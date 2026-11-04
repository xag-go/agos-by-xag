"use client";

import { useState, useTransition } from "react";
import type { ToolKeys } from "@/data/queries";
import { Button } from "@/shared/ui/button";
import { useAsk } from "@/shared/ui/confirm";
import { Field, Input } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import {
  addToolKey,
  removeToolKey,
  replaceToolKey,
  testToolKey,
  toolKeyName,
} from "./tool-keys-actions";
import { PanelSection } from "@/shared/ui/panel";

type Key = ToolKeys["keys"][number];
type Status = { error: string | null; saved?: boolean; text?: string };

const when = (at?: string | null) =>
  at ? new Date(at).toLocaleDateString() : "";

/** Workspace → Keys: keys for this workspace's own tools and scripts. He types
 * the app's name and pastes its key; Hermes keeps it for this workspace only and
 * hands it to the tools. The key is never shown again, only its last four. */
export function ToolKeysCard({
  workspaceId,
  data,
}: {
  workspaceId: string;
  data: ToolKeys | null;
}) {
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <p className="text-sm text-ink-2">
        Keys for the apps this workspace&apos;s tools and scripts use (for
        example Pixabay or OpenRouter). Type the app&apos;s name, paste its key
        and save. The key stays in this workspace only, and nobody sees it
        again: not you, not the agents, not the chat.
      </p>
      <PanelSection
        aria-labelledby="tool-keys-title"
        className="flex flex-col gap-4 p-5"
      >
        <h2
          id="tool-keys-title"
          className="font-display text-base font-semibold"
        >
          Keys
        </h2>
        {data === null ? (
          <p className="text-sm text-ink-2">
            The keys can&apos;t be shown right now. Try again in a minute.
          </p>
        ) : data.keys.length === 0 ? (
          <p className="text-sm text-ink-2">No keys yet.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {data.keys.map((k) => (
              <KeyRow key={k.name} workspaceId={workspaceId} item={k} />
            ))}
          </ul>
        )}
        {data !== null ? <AddKey workspaceId={workspaceId} /> : null}
      </PanelSection>
    </div>
  );
}

function KeyRow({ workspaceId, item }: { workspaceId: string; item: Key }) {
  const [status, setStatus] = useState<Status>({ error: null });
  const [busy, start] = useTransition();
  const [replacing, setReplacing] = useState(false);
  const [key, setKey] = useState("");
  const { dialog, confirm } = useAsk();
  const details = [
    item.saved
      ? item.endsWith
        ? `Ends with …${item.endsWith}`
        : "Saved"
      : "Not saved yet",
    item.savedAt ? `saved ${when(item.savedAt)}` : "",
    item.testedAt
      ? `tested ${when(item.testedAt)}${item.testOk === false ? " (didn't work)" : item.testOk ? " (works)" : ""}`
      : "",
  ].filter(Boolean);
  return (
    <li className="flex flex-col gap-2 rounded-lg bg-sunken px-3 py-2 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex min-w-0 flex-col">
          <span className="font-medium text-ink">{item.app}</span>
          <span className="text-xs text-ink-3">
            <code>{item.name}</code> · {details.join(" · ")}
          </span>
        </span>
        <span className="flex gap-2">
          <Button
            className="h-8"
            disabled={busy}
            onClick={() => {
              setReplacing((v) => !v);
              setStatus({ error: null });
            }}
          >
            Replace
          </Button>
          <Button
            className="h-8"
            disabled={busy || !item.saved}
            onClick={() => {
              start(async () => {
                const r = await testToolKey(workspaceId, item.name);
                setStatus(
                  r.error
                    ? { error: r.error }
                    : r.ok
                      ? { error: null, saved: true, text: r.message }
                      : { error: r.message ?? "It didn't work." },
                );
              });
            }}
          >
            {busy ? "Testing…" : "Test"}
          </Button>
          <Button
            className="h-8"
            variant="danger"
            disabled={busy}
            onClick={() => {
              void confirm({
                title: `Delete the ${item.app} key?`,
                body: "This workspace's tools and scripts can't use it any more.",
                confirmLabel: "Delete",
              }).then((yes) => {
                if (yes)
                  start(async () => {
                    setStatus(await removeToolKey(workspaceId, item.name));
                  });
              });
            }}
          >
            Delete
          </Button>
        </span>
      </div>
      {replacing ? (
        <div className="flex flex-wrap items-end gap-2">
          <Field label={`New ${item.app} key`} className="min-w-64 flex-1">
            <Input
              type="password"
              autoComplete="off"
              value={key}
              onChange={(e) => {
                setKey(e.target.value);
              }}
            />
          </Field>
          <Button
            variant="primary"
            disabled={busy || !key.trim()}
            onClick={() => {
              start(async () => {
                const r = await replaceToolKey(workspaceId, item.name, key);
                setStatus(r);
                if (!r.error) {
                  setKey("");
                  setReplacing(false);
                }
              });
            }}
          >
            {busy ? "Saving…" : "Save"}
          </Button>
        </div>
      ) : null}
      <FormStatus
        error={status.error}
        saved={status.saved}
        savedText={status.text ?? "Saved."}
      />
      {dialog}
    </li>
  );
}

function AddKey({ workspaceId }: { workspaceId: string }) {
  const [app, setApp] = useState("");
  const [key, setKey] = useState("");
  const [name, setName] = useState<{
    app: string;
    name?: string;
    url?: string;
    exists?: boolean;
    error?: string | null;
  }>({ app: "" });
  const [status, setStatus] = useState<Status>({ error: null });
  const [busy, start] = useTransition();
  const lookUp = (value: string) => {
    const typed = value.trim();
    if (!typed || typed === name.app) return;
    void toolKeyName(workspaceId, typed).then((r) => {
      setName({ app: typed, ...r });
    });
  };
  const shown = name.app === app.trim() ? name : null;
  return (
    <div className="grid gap-3 border-t border-line pt-4 sm:grid-cols-2">
      <Field label="App name">
        <Input
          value={app}
          placeholder="For example Pixabay"
          maxLength={60}
          onChange={(e) => {
            setApp(e.target.value);
          }}
          onBlur={(e) => {
            lookUp(e.target.value);
          }}
        />
      </Field>
      <Field label="Key">
        <Input
          type="password"
          autoComplete="off"
          value={key}
          onFocus={() => {
            lookUp(app);
          }}
          onChange={(e) => {
            setKey(e.target.value);
          }}
        />
      </Field>
      {shown?.error ? (
        <p className="text-xs text-danger sm:col-span-2">{shown.error}</p>
      ) : shown?.name ? (
        <p className="text-xs text-ink-3 sm:col-span-2">
          Tools will read it as <code>{shown.name}</code>
          {shown.exists ? " (Save replaces the key saved now)" : ""}
          {shown.url ? (
            <>
              {" · "}
              <a
                href={shown.url}
                target="_blank"
                rel="noreferrer"
                className="underline"
              >
                Get a key
              </a>
            </>
          ) : null}
        </p>
      ) : null}
      <div className="flex flex-col gap-2 sm:col-span-2">
        <div>
          <Button
            variant="primary"
            disabled={busy || !app.trim() || !key.trim()}
            onClick={() => {
              start(async () => {
                const r = await addToolKey(workspaceId, app, key);
                setStatus({
                  error: r.error,
                  saved: !r.error,
                  text: r.name ? `Saved as ${r.name}.` : "Saved.",
                });
                if (!r.error) {
                  setKey("");
                  setApp("");
                  setName({ app: "" });
                }
              });
            }}
          >
            {busy ? "Saving…" : "Save"}
          </Button>
        </div>
        <FormStatus
          error={status.error}
          saved={status.saved}
          savedText={status.text ?? "Saved."}
        />
      </div>
    </div>
  );
}
