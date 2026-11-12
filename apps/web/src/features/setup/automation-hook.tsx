"use client";

import { useState, useTransition } from "react";
import type { Automation, AutomationEvent, HookCondition } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { useAsk } from "@/shared/ui/confirm";
import { DialogCloseButton, RouteDialog } from "@/shared/ui/dialog";
import { Field, Input, Select } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { formatWhen } from "@/shared/format";
import { saveHook, saveHooksAddress, showHookSecret } from "./actions";

const statusText: Record<AutomationEvent["status"], string> = {
  pending: "Waiting for the current run",
  started: "Started the work",
  duplicate: "Already received",
  filtered: "Not an event it starts on",
  rejected: "Refused",
  off: "Automation was off",
};

const opText: Record<HookCondition["op"], string> = {
  is: "is one of",
  is_not: "is not one of",
  contains: "contains",
  not_contains: "doesn't contain",
};

type Line = {
  when: string;
  field: string;
  op: HookCondition["op"];
  values: string;
};

const toLine = (c: HookCondition): Line => ({
  when: c.when ?? "",
  field: c.field,
  op: c.op ?? "is",
  values: (c.values ?? []).join(", "),
});

const fromLine = (l: Line): HookCondition => ({
  when: l.when || null,
  field: l.field.trim(),
  op: l.op,
  values: l.values
    .split(/[,\n]/)
    .map((v) => v.trim())
    .filter(Boolean),
});

/** The automation's webhook: its address, signing secret, events and deliveries. */
export function AutomationHookDialog({
  workspaceId,
  automation,
  events,
  publicUrl,
  closeHref,
}: {
  workspaceId: string;
  automation: Automation;
  events: AutomationEvent[];
  publicUrl: string;
  closeHref: string;
}) {
  const hook = automation.hook ?? null;
  const [busy, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);
  const [secret, setSecret] = useState("");
  // A signing secret AGOS just made: shown here once, never again.
  const [madeSecret, setMadeSecret] = useState<string | null>(null);
  const [eventList, setEventList] = useState((hook?.events ?? []).join(", "));
  const [address, setAddress] = useState(publicUrl);
  const [lines, setLines] = useState<Line[]>(
    (hook?.conditions ?? []).map(toLine),
  );
  const setLine = (i: number, change: Partial<Line>) => {
    setLines((all) => all.map((l, j) => (j === i ? { ...l, ...change } : l)));
  };
  const { dialog, confirm } = useAsk();
  const url = hook
    ? `${publicUrl || "https://<your public address>"}${hook.path}`
    : "";

  const run = (
    fn: () => Promise<{ error: string | null; secret?: string }>,
  ) => {
    setError(null);
    setSaved(false);
    start(async () => {
      const result = await fn();
      if (result.error) setError(result.error);
      else setSaved(true);
      if (result.secret) setMadeSecret(result.secret);
    });
  };
  const events_ = () =>
    eventList
      .split(/[,\n]/)
      .map((e) => e.trim())
      .filter(Boolean);

  return (
    <RouteDialog
      closeHref={closeHref}
      label={`${automation.name} webhook`}
      size="md"
    >
      {dialog}
      <div className="flex max-h-[92dvh] flex-col">
        <header className="flex items-start gap-3 border-b border-line px-5 py-4">
          <div className="flex-1">
            <h2 className="font-display text-xl font-semibold">
              Webhook · {automation.name}
            </h2>
            <p className="mt-0.5 text-sm text-ink-2">
              Another app sends a message to this address the moment something
              happens; the work starts at once, with what it sent.
            </p>
          </div>
          <DialogCloseButton />
        </header>

        <div className="flex flex-col gap-5 overflow-y-auto px-5 py-5">
          {!hook ? (
            <div className="flex flex-col items-start gap-3">
              <p className="text-sm text-ink-2">
                This automation only starts on its schedule.
              </p>
              <Button
                variant="primary"
                disabled={busy}
                onClick={() => {
                  run(() => saveHook(workspaceId, automation.id, { on: true }));
                }}
              >
                Turn on the webhook
              </Button>
            </div>
          ) : (
            <>
              <Field
                label="Public address of this machine"
                hint="Once for all automations: the https address that reaches AGOS's webhook relay (a tunnel or your server)."
              >
                <div className="flex gap-2">
                  <Input
                    value={address}
                    placeholder="https://hooks.example.com"
                    onChange={(e) => {
                      setAddress(e.target.value);
                    }}
                  />
                  <Button
                    disabled={busy || address === publicUrl}
                    onClick={() => {
                      run(() =>
                        saveHooksAddress(workspaceId, automation.id, address),
                      );
                    }}
                  >
                    Save
                  </Button>
                </div>
              </Field>

              <div className="flex flex-col gap-1.5">
                <p className="text-sm font-medium">Webhook address</p>
                <div className="flex items-center gap-2">
                  <code className="min-w-0 flex-1 break-all rounded-lg bg-sunken px-3 py-2 text-xs">
                    {url}
                  </code>
                  <Button
                    disabled={!publicUrl}
                    onClick={() => {
                      void navigator.clipboard.writeText(url).then(() => {
                        setCopied(true);
                        setTimeout(() => {
                          setCopied(false);
                        }, 1500);
                      });
                    }}
                  >
                    {copied ? "Copied" : "Copy"}
                  </Button>
                </div>
                <p className="text-xs text-ink-3">
                  Keep it private: anyone with it can start this automation
                  {hook.signed
                    ? " (and they also need the signing secret)"
                    : ""}
                  .{!publicUrl && " Save the public address above first."}
                </p>
              </div>

              <Field
                label="Signing secret"
                hint={
                  madeSecret
                    ? "Copy it now and paste it in the other app: AGOS shows it only this once. Every delivery must be signed with it (HMAC-SHA256 of the body, header x-agos-signature)."
                    : hook.secretWaiting
                      ? "AGOS made a signing secret when this webhook was saved. Show it once and paste it in the other app: until then its deliveries are refused."
                      : hook.signed
                        ? "Set: every delivery must be signed with it (HMAC-SHA256 of the body, header x-agos-signature). Paste a new one to change it."
                        : "Unsigned: the address alone lets a delivery in. Make a secret, or paste the one the other app shows (e.g. a whsec_… secret); unsigned deliveries are then refused."
                }
              >
                <div className="flex gap-2">
                  <Input
                    type={madeSecret ? "text" : "password"}
                    autoComplete="off"
                    readOnly={Boolean(madeSecret)}
                    value={madeSecret ?? secret}
                    placeholder={hook.signed ? "•••••••• (set)" : "whsec_…"}
                    onChange={(e) => {
                      setSecret(e.target.value);
                    }}
                  />
                  {madeSecret ? (
                    <Button
                      onClick={() => {
                        void navigator.clipboard.writeText(madeSecret);
                      }}
                    >
                      Copy
                    </Button>
                  ) : hook.secretWaiting ? (
                    <Button
                      disabled={busy}
                      onClick={() => {
                        run(() => showHookSecret(workspaceId, automation.id));
                      }}
                    >
                      Show it once
                    </Button>
                  ) : (
                    <Button
                      disabled={busy}
                      onClick={() => {
                        run(() =>
                          saveHook(workspaceId, automation.id, {
                            on: true,
                            newSecret: true,
                            events: events_(),
                          }),
                        );
                      }}
                    >
                      {hook.signed ? "Make a new secret" : "Make a secret"}
                    </Button>
                  )}
                </div>
              </Field>

              <Field
                label="Only these events"
                hint="Comma-separated, e.g. spaces.task.moved, spaces.task.created. Empty = every delivery starts it."
              >
                <Input
                  value={eventList}
                  placeholder="every event"
                  onChange={(e) => {
                    setEventList(e.target.value);
                  }}
                />
              </Field>

              <section className="flex flex-col gap-2">
                <div>
                  <p className="text-sm font-medium">Only if</p>
                  <p className="text-xs text-ink-3">
                    A delivery starts the work only when every line holds; any
                    other delivery is dropped before anything runs (no run, no
                    tokens, no message). Field = where the value is in what the
                    app sends, e.g. data.to.name.
                  </p>
                </div>
                {lines.length === 0 && (
                  <p className="text-sm text-ink-3">
                    No line: every delivery of these events starts it.
                  </p>
                )}
                {lines.map((l, i) => (
                  <div
                    key={i}
                    className="grid grid-cols-1 gap-2 rounded-lg border border-line p-2 sm:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1fr)]"
                  >
                    <Select
                      aria-label="For which event"
                      value={l.when}
                      onChange={(e) => {
                        setLine(i, { when: e.target.value });
                      }}
                    >
                      <option value="">Every event</option>
                      {[
                        ...new Set([...events_(), ...(l.when ? [l.when] : [])]),
                      ].map((ev) => (
                        <option key={ev} value={ev}>
                          When {ev}
                        </option>
                      ))}
                    </Select>
                    <Input
                      aria-label="Field"
                      value={l.field}
                      placeholder="data.to.name"
                      onChange={(e) => {
                        setLine(i, { field: e.target.value });
                      }}
                    />
                    <Select
                      aria-label="Test"
                      value={l.op}
                      onChange={(e) => {
                        setLine(i, { op: e.target.value as Line["op"] });
                      }}
                    >
                      {Object.entries(opText).map(([op, text]) => (
                        <option key={op} value={op}>
                          {text}
                        </option>
                      ))}
                    </Select>
                    <div className="flex gap-2 sm:col-span-3">
                      <Input
                        aria-label="Values"
                        className="flex-1"
                        value={l.values}
                        placeholder="todo, final"
                        onChange={(e) => {
                          setLine(i, { values: e.target.value });
                        }}
                      />
                      <Button
                        variant="ghost"
                        aria-label="Remove this line"
                        onClick={() => {
                          setLines((all) => all.filter((_, j) => j !== i));
                        }}
                      >
                        Remove
                      </Button>
                    </div>
                  </div>
                ))}
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setLines((all) => [
                        ...all,
                        { when: "", field: "", op: "is", values: "" },
                      ]);
                    }}
                  >
                    Add a line
                  </Button>
                  {(hook.otherFilters ?? 0) > 0 && (
                    <span className="text-xs text-ink-3">
                      + {hook.otherFilters} more set in the engine directly
                      (kept as they are)
                    </span>
                  )}
                </div>
              </section>

              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="primary"
                  disabled={busy}
                  onClick={() => {
                    run(() =>
                      saveHook(workspaceId, automation.id, {
                        on: true,
                        secret: secret ? secret : undefined,
                        events: events_(),
                        conditions: lines.map(fromLine),
                      }),
                    );
                    setSecret("");
                  }}
                >
                  Save
                </Button>
                {hook.signed && (
                  <Button
                    disabled={busy}
                    onClick={() => {
                      run(() =>
                        saveHook(workspaceId, automation.id, {
                          on: true,
                          secret: "",
                          events: events_(),
                        }),
                      );
                    }}
                  >
                    Remove secret
                  </Button>
                )}
                <Button
                  variant="ghost"
                  disabled={busy}
                  onClick={() => {
                    void (async () => {
                      const ok = await confirm({
                        title: "Make a new address?",
                        body: "The current address stops working at once. Paste the new one in the other app.",
                        confirmLabel: "New address",
                      });
                      if (ok)
                        run(() =>
                          saveHook(workspaceId, automation.id, {
                            on: true,
                            newAddress: true,
                            events: events_(),
                          }),
                        );
                    })();
                  }}
                >
                  New address
                </Button>
                <Button
                  variant="ghost"
                  disabled={busy}
                  onClick={() => {
                    void (async () => {
                      const ok = await confirm({
                        title: "Turn off the webhook?",
                        body: "The address stops working; the automation keeps its schedule.",
                        confirmLabel: "Turn off",
                        danger: true,
                      });
                      if (ok)
                        run(() =>
                          saveHook(workspaceId, automation.id, { on: false }),
                        );
                    })();
                  }}
                >
                  Turn off
                </Button>
                <FormStatus error={error} saved={saved} className="text-xs" />
              </div>

              <section className="flex flex-col gap-2 border-t border-line pt-4">
                <h3 className="text-sm font-medium">Last deliveries</h3>
                {events.length === 0 ? (
                  <p className="text-sm text-ink-3">Nothing received yet.</p>
                ) : (
                  <ul className="flex flex-col divide-y divide-line text-sm">
                    {events.map((e) => (
                      <li
                        key={e.id}
                        className="flex flex-wrap items-baseline gap-x-2 py-1.5"
                      >
                        <span
                          className={cn(
                            "text-xs",
                            e.status === "started"
                              ? "text-success"
                              : e.status === "rejected"
                                ? "text-danger"
                                : "text-ink-2",
                          )}
                        >
                          {statusText[e.status]}
                        </span>
                        <span className="text-xs text-ink-3">
                          {formatWhen(e.receivedAt)}
                          {e.event && ` · ${e.event}`}
                          {e.planId ? ` · plan #${String(e.planId)}` : ""}
                        </span>
                        {e.preview && (
                          <span className="w-full truncate text-ink-2">
                            {e.preview}
                          </span>
                        )}
                        {e.detail && e.status !== "started" && (
                          <span className="w-full text-xs text-ink-3">
                            {e.detail}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </>
          )}
          {!hook && <FormStatus error={error} className="text-xs" />}
        </div>
      </div>
    </RouteDialog>
  );
}
