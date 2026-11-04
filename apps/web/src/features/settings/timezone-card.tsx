"use client";

import { useState, useSyncExternalStore, useTransition } from "react";
import { Button } from "@/shared/ui/button";
import { saveTimezone } from "./preferences-actions";

const noop = () => () => {};
let cachedZones: string[] | null = null;

// Browser-only values (the server's clock is not his): read after hydration.
function useClient<T>(read: () => T, server: T): T {
  return useSyncExternalStore(noop, read, () => server);
}

function zones(): string[] {
  if (cachedZones) return cachedZones;
  try {
    cachedZones = Intl.supportedValuesOf("timeZone");
  } catch {
    cachedZones = [];
  }
  return cachedZones;
}

function deviceZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return "";
  }
}

function nowIn(zone: string): string {
  try {
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: zone,
      weekday: "short",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date());
  } catch {
    return "";
  }
}

const NONE: string[] = [];

export function TimezoneCard({ initial }: { initial: string }) {
  const all = useClient(zones, NONE);
  const device = useClient(deviceZone, "");
  const [value, setValue] = useState(initial);
  const [saved, setSaved] = useState(initial);
  const [note, setNote] = useState<string | null>(null);
  const [busy, start] = useTransition();
  const options = value && !all.includes(value) ? [value, ...all] : all;

  const save = (zone: string) => {
    setNote(null);
    start(async () => {
      const r = await saveTimezone(zone);
      if (r.error) {
        setNote(r.error);
      } else {
        setSaved(zone);
        setNote("Saved.");
      }
    });
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <select
          aria-label="Timezone"
          value={value}
          disabled={busy}
          onChange={(e) => {
            setValue(e.target.value);
            setNote(null);
          }}
          className="h-9 w-72 rounded-lg border border-line bg-panel px-3 text-sm"
        >
          <option value="">Not set (this server&apos;s timezone)</option>
          {options.map((zone) => (
            <option key={zone} value={zone}>
              {zone.replaceAll("_", " ")}
            </option>
          ))}
        </select>
        <Button
          variant="primary"
          disabled={busy || value === saved}
          onClick={() => save(value)}
        >
          Save
        </Button>
        {device && device !== value ? (
          <Button
            disabled={busy}
            onClick={() => {
              setValue(device);
              save(device);
            }}
          >
            Use this device’s ({device.replaceAll("_", " ")})
          </Button>
        ) : null}
        {note ? (
          <span role="status" className="text-sm text-ink-2">
            {note}
          </span>
        ) : null}
      </div>
      {saved && device ? (
        <p className="text-sm text-ink-3">It is {nowIn(saved)} there now.</p>
      ) : null}
    </div>
  );
}
