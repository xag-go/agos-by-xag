"use client";

import { useEffect, useState, useTransition } from "react";
import type { PushDevice } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { formatWhen } from "@/shared/format";
import {
  pushKey,
  subscribePush,
  testPush,
  unsubscribePush,
} from "./push-actions";
import { PanelSection } from "@/shared/ui/panel";

type State =
  | "checking"
  | "unsupported" // no service worker / Push API here (e.g. iPhone Safari outside the installed app)
  | "blocked" // he refused notifications for this site in the browser
  | "off"
  | "on";

/** AGOS's own notifications on this device (the installed app or this browser),
 *  and every device that asked for them. */
export function PushDevices({ devices }: { devices: PushDevice[] }) {
  const [state, setState] = useState<State>("checking");
  const [endpoint, setEndpoint] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, start] = useTransition();

  useEffect(() => {
    // Asked after mount: the browser's push state is only known in the browser.
    void (async () => {
      if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
        return { state: "unsupported" as const, endpoint: null };
      }
      if (Notification.permission === "denied") {
        return { state: "blocked" as const, endpoint: null };
      }
      const r = await navigator.serviceWorker.ready;
      const sub = await r.pushManager.getSubscription();
      return {
        state: sub ? ("on" as const) : ("off" as const),
        endpoint: sub?.endpoint ?? null,
      };
    })().then((found) => {
      setEndpoint(found.endpoint);
      setState(found.state);
    });
  }, []);

  const mine = devices.find((d) => d.endpoint === endpoint);

  const enable = () =>
    start(async () => {
      setNote(null);
      try {
        const permission = await Notification.requestPermission();
        if (permission !== "granted") {
          setState(permission === "denied" ? "blocked" : "off");
          return;
        }
        const registration = await navigator.serviceWorker.ready;
        const sub = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: keyBytes(await pushKey()),
        });
        const json = sub.toJSON();
        const r = await subscribePush({
          endpoint: sub.endpoint,
          p256dh: json.keys?.p256dh ?? "",
          auth: json.keys?.auth ?? "",
          label: deviceLabel(),
        });
        if (r.error) {
          setNote(r.error);
          await sub.unsubscribe();
          return;
        }
        setEndpoint(sub.endpoint);
        setState("on");
      } catch (e) {
        setNote(
          e instanceof Error ? e.message : "Could not turn notifications on",
        );
      }
    });

  const disable = (which: string) =>
    start(async () => {
      setNote(null);
      if (which === endpoint) {
        const registration = await navigator.serviceWorker.ready;
        await (await registration.pushManager.getSubscription())?.unsubscribe();
        setEndpoint(null);
        setState("off");
      }
      const r = await unsubscribePush(which);
      if (r.error) setNote(r.error);
    });

  const test = () =>
    start(async () => {
      const r = await testPush();
      setNote(
        r.error ??
          (r.sent === 0
            ? "No device is subscribed."
            : `Sent to ${String(r.sent)} device${r.sent === 1 ? "" : "s"}.`),
      );
    });

  return (
    <PanelSection>
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
        <div>
          <p className="text-sm font-medium">On this device</p>
          <p className="text-xs text-ink-3">
            {state === "checking" && "Checking…"}
            {state === "unsupported" &&
              "This browser can't receive notifications. On iPhone, install AGOS to the Home Screen first (Share → Add to Home Screen) and open it from there."}
            {state === "blocked" &&
              "Notifications are blocked for AGOS in this browser's site settings. Allow them there, then come back."}
            {state === "off" &&
              "An agent waiting for your approval, AGOS's own cards and finished answers reach this device, even with AGOS closed."}
            {state === "on" && "This device gets AGOS's notifications."}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {state === "off" && (
            <Button variant="primary" disabled={busy} onClick={enable}>
              Turn on
            </Button>
          )}
          {state === "on" && (
            <>
              <Button disabled={busy} onClick={test}>
                Send a test
              </Button>
              <Button
                disabled={busy}
                onClick={() => {
                  if (endpoint) disable(endpoint);
                }}
              >
                Turn off
              </Button>
            </>
          )}
        </div>
      </div>
      {note && <p className="px-5 pb-3 text-xs text-ink-2">{note}</p>}
      {devices.length > 0 && (
        <ul className="divide-y divide-line border-t border-line">
          {devices.map((d) => (
            <li
              key={d.id}
              className="flex flex-wrap items-center justify-between gap-3 px-5 py-2.5 text-sm"
            >
              <span>
                {d.label || "A device"}
                {d.endpoint === endpoint && (
                  <span className="ml-2 rounded-md bg-sunken px-1.5 text-xs text-ink-2">
                    this one
                  </span>
                )}
                <span className="ml-2 text-xs text-ink-3">
                  since {formatWhen(d.createdAt)}
                </span>
              </span>
              {d.endpoint !== endpoint && (
                <Button
                  disabled={busy}
                  onClick={() => {
                    disable(d.endpoint);
                  }}
                >
                  Remove
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {mine === undefined && state === "on" && (
        <p className="border-t border-line px-5 py-2.5 text-xs text-ink-3">
          This browser has a subscription AGOS doesn&apos;t know (made on
          another server?). Turn off, then on again.
        </p>
      )}
    </PanelSection>
  );
}

function keyBytes(b64url: string): Uint8Array<ArrayBuffer> {
  const b64 = b64url.replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(b64 + "=".repeat((4 - (b64.length % 4)) % 4));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

/** "Android · Chrome", "iPhone · installed", … (what the owner recognises). */
function deviceLabel(): string {
  const ua = navigator.userAgent;
  const device = /iPhone/.test(ua)
    ? "iPhone"
    : /iPad/.test(ua)
      ? "iPad"
      : /Android/.test(ua)
        ? "Android"
        : /Mac/.test(ua)
          ? "Mac"
          : /Windows/.test(ua)
            ? "Windows"
            : /Linux/.test(ua)
              ? "Linux"
              : "Device";
  const installed = window.matchMedia("(display-mode: standalone)").matches;
  const browser = /Edg\//.test(ua)
    ? "Edge"
    : /Firefox\//.test(ua)
      ? "Firefox"
      : /Chrome\//.test(ua)
        ? "Chrome"
        : /Safari\//.test(ua)
          ? "Safari"
          : "browser";
  return `${device} · ${installed ? "installed app" : browser}`;
}
