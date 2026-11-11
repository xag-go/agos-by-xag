"use client";

import { useEffect, useRef, useState } from "react";

type State = "loading" | "live" | "off" | "error";

/** The workspace's screen, refreshed about once a second while the page is
 * visible. Watch only: the agent drives it, nothing here sends input. */
export function LiveScreen({
  workspaceId,
  idleStopMinutes,
}: {
  workspaceId: string;
  /** Hermes's bot_desktop.idle_stop_minutes (0: never; null: not known). */
  idleStopMinutes: number | null;
}) {
  const [src, setSrc] = useState<string | null>(null);
  const [state, setState] = useState<State>("loading");
  const [at, setAt] = useState<Date | null>(null);
  const current = useRef<string | null>(null);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let xhr: XMLHttpRequest | undefined;

    const show = (blob: Blob) => {
      const url = URL.createObjectURL(blob);
      if (current.current) URL.revokeObjectURL(current.current);
      current.current = url;
      setSrc(url);
      setState("live");
      setAt(new Date());
    };

    const tick = () => {
      if (stopped) return;
      if (document.visibilityState !== "visible") {
        timer = setTimeout(tick, 1000);
        return;
      }
      xhr = new XMLHttpRequest();
      xhr.open("GET", `/api/w/${workspaceId}/screen?w=1440&t=${Date.now()}`);
      xhr.responseType = "blob";
      xhr.onload = () => {
        if (stopped || !xhr) return;
        if (xhr.status === 200) show(xhr.response as Blob);
        else if (xhr.status === 204 || xhr.status === 404) setState("off");
        else setState("error");
        timer = setTimeout(tick, xhr.status === 200 ? 1000 : 4000);
      };
      xhr.onerror = () => {
        if (stopped) return;
        setState("error");
        timer = setTimeout(tick, 4000);
      };
      xhr.send();
    };
    tick();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      xhr?.abort();
      if (current.current) URL.revokeObjectURL(current.current);
    };
  }, [workspaceId]);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2 text-sm text-ink-2">
        <span
          className={`size-2 rounded-full ${state === "live" ? "bg-green-500" : "bg-line"}`}
        />
        {state === "live" && (
          <span>Live{at ? ` · ${at.toLocaleTimeString()}` : ""}</span>
        )}
        {state === "loading" && <span>Connecting…</span>}
        {state === "off" && (
          <span>
            The screen is off right now. It turns on by itself when an agent
            uses the browser or the desktop
            {idleStopMinutes === null
              ? ", and it turns off by itself when it isn't used."
              : idleStopMinutes === 0
                ? "."
                : `, and goes off after ${String(idleStopMinutes)} ${idleStopMinutes === 1 ? "minute" : "minutes"} without use.`}
          </span>
        )}
        {state === "error" && (
          <span>Can&apos;t reach the screen. Trying again…</span>
        )}
      </div>
      <div className="overflow-hidden rounded-xl border border-line bg-sunken">
        {src && state !== "off" ? (
          // eslint-disable-next-line @next/next/no-img-element -- live blob, not an asset
          <img
            src={src}
            alt="What the agent sees on its screen"
            className="block h-auto w-full"
          />
        ) : (
          <div className="flex aspect-[16/10] items-center justify-center text-sm text-ink-3">
            {state === "off" ? "Nothing on screen" : ""}
          </div>
        )}
      </div>
    </div>
  );
}
