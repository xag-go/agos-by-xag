"use client";

import { useEffect, useMemo, useState } from "react";
import { renderSVG } from "uqr";
import type { RemoteAccess } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { useAsk } from "@/shared/ui/confirm";
import { Field, Input } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import {
  activateRemoteAccess,
  readRemoteAccess,
  saveAlsoAllow,
  turnOffRemoteAccess,
} from "./remote-access-actions";
import { PanelSection } from "@/shared/ui/panel";

/** The states that wait for the owner in another tab: the card polls them. */
const WAITING = ["waiting-login", "needs-https"];
const POLL_MS = 3000;

const STATE_WORDS: Record<string, string> = {
  on: "On",
  "waiting-login": "Waiting for Tailscale login",
  "needs-https": "Waiting for Tailscale",
};

/** Settings → Access → "Use AGOS from other devices": one click turns on
 * Tailscale for AGOS (the core runs `tailscale up` and `tailscale serve`,
 * actions/remote_access.py); the card shows the login link, then the address
 * and its QR code. */
export function RemoteAccessCard({
  initial,
}: {
  initial: RemoteAccess | null;
}) {
  const [view, setView] = useState<RemoteAccess | null>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { dialog, confirm } = useAsk();
  const state = view?.state ?? "error";
  const waiting = WAITING.includes(state);

  useEffect(() => {
    if (!waiting) return;
    let stopped = false;
    const timer = setInterval(() => {
      // A hidden tab polls nothing; the owner is logging in in another tab, so
      // the poll runs again the moment he comes back.
      if (document.visibilityState !== "visible") return;
      void readRemoteAccess().then((answer) => {
        if (!stopped && answer.ok) setView(answer.data);
      });
    }, POLL_MS);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [waiting]);

  const run = async (
    work: () => ReturnType<typeof activateRemoteAccess>,
  ): Promise<void> => {
    setBusy(true);
    setError(null);
    const answer = await work();
    setBusy(false);
    if (answer.ok) setView(answer.data);
    else setError(answer.error);
  };

  const onTurnOff = async () => {
    const ok = await confirm({
      title: "Turn off access from other devices?",
      body: "Your phone and other computers can't open AGOS any more. It still opens on this machine. Tailscale itself stays installed and logged in.",
      confirmLabel: "Turn off",
      danger: true,
    });
    if (ok) await run(turnOffRemoteAccess);
  };

  return (
    <PanelSection className="flex flex-col gap-4 p-5">
      {dialog}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display font-semibold">
          Use AGOS from other devices
        </h2>
        <span
          className={
            state === "on"
              ? "rounded-full bg-success/15 px-2.5 py-0.5 text-xs font-medium text-success"
              : "rounded-full bg-sunken px-2.5 py-0.5 text-xs font-medium text-ink-2"
          }
        >
          {STATE_WORDS[state] ?? "Off"}
        </span>
      </div>

      {view === null ? (
        <p className="text-sm text-ink-2">
          The core isn&apos;t answering. Reload the page in a moment.
        </p>
      ) : state === "on" ? (
        <OnView
          view={view}
          busy={busy}
          onTurnOff={() => void onTurnOff()}
          onSaved={setView}
        />
      ) : waiting ? (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-ink-2">{view.message}</p>
          {view.loginUrl ? (
            <a
              href={view.loginUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="agos-button inline-flex h-12 items-center justify-center self-start rounded-xl bg-accent px-6 text-base font-semibold text-accent-ink hover:opacity-85"
            >
              {state === "needs-https"
                ? "Turn on HTTPS in Tailscale"
                : "Log in to Tailscale"}
            </a>
          ) : null}
          <p
            aria-live="polite"
            className="flex items-center gap-2 text-sm text-ink-3"
          >
            <span className="size-2 animate-pulse rounded-full bg-accent" />
            Waiting… this card checks every few seconds.
          </p>
          <Button
            variant="ghost"
            className="self-start"
            disabled={busy}
            onClick={() => void run(turnOffRemoteAccess)}
          >
            Cancel
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {state === "off" ? (
            <p className="text-sm text-ink-2">
              Open AGOS on your phone or another computer, safely: it goes
              through your own private Tailscale network, never the open
              internet, and only your Tailscale account gets in.
            </p>
          ) : (
            <p className="text-sm text-ink-2">{view.message}</p>
          )}
          {view.command ? <Command text={view.command} /> : null}
          {view.warning ? (
            <p className="text-sm text-ink-2">{view.warning}</p>
          ) : null}
          <Button
            variant="primary"
            className="self-start"
            disabled={busy}
            onClick={() => void run(activateRemoteAccess)}
          >
            {busy
              ? "Activating…"
              : state === "error"
                ? "Try again"
                : "Activate"}
          </Button>
        </div>
      )}
      <FormStatus error={error} />
    </PanelSection>
  );
}

function OnView({
  view,
  busy,
  onTurnOff,
  onSaved,
}: {
  view: RemoteAccess;
  busy: boolean;
  onTurnOff: () => void;
  onSaved: (view: RemoteAccess) => void;
}) {
  const svg = useMemo(
    () => (view.address ? renderSVG(view.address, { border: 2 }) : ""),
    [view.address],
  );
  return (
    <div className="flex flex-col gap-4">
      {view.warning ? (
        <p role="alert" className="text-sm text-danger">
          {view.warning}
        </p>
      ) : null}
      <div className="flex flex-wrap items-start gap-5">
        {/* The SVG is made here by uqr from the address (no outside HTML). */}
        <div
          role="img"
          aria-label={`QR code of ${view.address}`}
          className="size-36 shrink-0 overflow-hidden rounded-lg bg-white"
          dangerouslySetInnerHTML={{ __html: svg }}
        />
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          <a
            href={view.address}
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium break-all text-ink underline-offset-2 hover:underline"
          >
            {view.address}
          </a>
          <ol className="flex list-decimal flex-col gap-1 pl-5 text-sm text-ink-2">
            <li>
              Install Tailscale on your phone or computer (App Store, Play Store
              or{" "}
              <a
                href="https://tailscale.com/download"
                target="_blank"
                rel="noopener noreferrer"
                className="underline underline-offset-2"
              >
                tailscale.com/download
              </a>
              ).
            </li>
            <li>
              Log in with the same account
              {view.user ? (
                <>
                  {" "}
                  (<span className="text-ink">{view.user}</span>)
                </>
              ) : null}
              .
            </li>
            <li>Scan this code, or open the address.</li>
          </ol>
        </div>
      </div>
      <AlsoAllow logins={view.alsoAllow ?? []} onSaved={onSaved} />
      <Button
        variant="danger"
        className="self-start"
        disabled={busy}
        onClick={onTurnOff}
      >
        {busy ? "Turning off…" : "Turn off"}
      </Button>
    </div>
  );
}

/** Optional: more Tailscale logins let in (family, team). */
function AlsoAllow({
  logins,
  onSaved,
}: {
  logins: string[];
  onSaved: (view: RemoteAccess) => void;
}) {
  const [open, setOpen] = useState(logins.length > 0);
  const [text, setText] = useState(logins.join(", "));
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  if (!open) {
    return (
      <Button
        variant="ghost"
        className="self-start px-0"
        onClick={() => setOpen(true)}
      >
        + Also allow someone else&apos;s Tailscale login
      </Button>
    );
  }
  const onSave = async () => {
    setBusy(true);
    setError(null);
    setSaved(false);
    const answer = await saveAlsoAllow(text.split(/[\s,]+/).filter(Boolean));
    setBusy(false);
    if (!answer.ok) {
      setError(answer.error);
      return;
    }
    setText((answer.data.alsoAllow ?? []).join(", "));
    setSaved(true);
    onSaved(answer.data);
  };
  return (
    <div className="flex flex-col gap-2 border-t border-line pt-3">
      <Field
        label="Also allow (optional)"
        hint="Other Tailscale logins that may open AGOS, like a family or team member. Separate them with commas. They need to be in your tailnet too."
      >
        <Input
          value={text}
          placeholder="name@gmail.com"
          onChange={(e) => {
            setText(e.target.value);
            setSaved(false);
          }}
        />
      </Field>
      <div className="flex items-center gap-3">
        <Button disabled={busy} onClick={() => void onSave()}>
          {busy ? "Saving…" : "Save"}
        </Button>
        <FormStatus error={error} saved={saved} />
      </div>
    </div>
  );
}

function Command({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-center gap-2 rounded-lg border border-line bg-sunken px-3 py-2">
      <code className="min-w-0 flex-1 text-sm break-all text-ink">{text}</code>
      <Button
        variant="ghost"
        className="h-7 px-2 text-xs"
        onClick={() => {
          void navigator.clipboard?.writeText(text).then(() => setCopied(true));
        }}
      >
        {copied ? "Copied" : "Copy"}
      </Button>
    </div>
  );
}
