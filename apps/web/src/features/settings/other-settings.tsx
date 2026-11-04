"use client";

import { useState, useTransition } from "react";
import type {
  AccountLimitView,
  BackupStatus,
  NotificationRule,
  Rehearsal,
  UsagePrefs,
} from "@/data/types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { Input, Select } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { Switch } from "@/shared/ui/switch";
import { OpsWarnings } from "./ops-warnings";
import { formatWhen } from "@/shared/format";
import {
  rehearseRestore,
  runBackup,
  setBackupPassword,
  setBackupSchedule,
} from "./backup-actions";
import { saveNotifications, saveUsagePrefs } from "./preferences-actions";
import { Panel, PanelSection } from "@/shared/ui/panel";

/** Real account limits from Hermes, the owner's warn / pause thresholds. */
export function UsageLimits({
  limits,
  prefs,
}: {
  limits: AccountLimitView[];
  prefs: UsagePrefs;
}) {
  const [enabled, setEnabled] = useState(prefs.enabled ?? true);
  const [warnAt, setWarnAt] = useState(prefs.warnAt ?? 80);
  const [pauseAt, setPauseAt] = useState(prefs.pauseAt ?? 100);
  const [status, setStatus] = useState<{
    error: string | null;
    saved: boolean;
  }>({
    error: null,
    saved: false,
  });
  const [busy, start] = useTransition();
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-sm font-medium">Use account limits</p>
          <p className="text-xs text-ink-3">
            Everything new waits while an account is at the pause level — new
            Kanban cards, schedules and chat replies (Hermes&apos;s own pause
            holds each workspace); work already running goes on.
          </p>
        </div>
        <Switch
          defaultOn={enabled}
          label="Use account limits"
          onChange={(on) => {
            setEnabled(on);
          }}
        />
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm text-ink-2">
        Warn me at
        <Input
          type="number"
          min={1}
          max={100}
          value={warnAt}
          onChange={(e) => {
            setWarnAt(Number(e.target.value));
          }}
          className="!w-20"
          aria-label="Warning threshold in percent"
        />
        % and pause new runs at
        <Input
          type="number"
          min={1}
          max={100}
          value={pauseAt}
          onChange={(e) => {
            setPauseAt(Number(e.target.value));
          }}
          className="!w-20"
          aria-label="Pause threshold in percent"
        />
        %
        <Button
          disabled={busy}
          onClick={() => {
            start(async () => {
              const r = await saveUsagePrefs({ enabled, warnAt, pauseAt });
              setStatus({ error: r.error, saved: !r.error });
            });
          }}
        >
          Save
        </Button>
        <FormStatus error={status.error} saved={status.saved} />
      </div>
      {limits.length === 0 ? (
        <p className="text-sm text-ink-3">
          No account reports its limits right now. Subscriptions logged in
          through Hermes (Claude, OpenAI Codex) show their session and weekly
          use here.
        </p>
      ) : (
        <ul className="flex flex-col gap-4">
          {limits.map((l) => (
            <Panel as="li" key={l.provider} className="p-5">
              <p className="font-medium">{l.label}</p>
              <ul className="mt-3 flex flex-col gap-3">
                {l.windows.map((w) => {
                  const used = w.usedPercent ?? 0;
                  const tone =
                    used >= pauseAt ? "danger" : used >= warnAt ? "warn" : "ok";
                  return (
                    <li key={w.label}>
                      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                        <span className="text-ink-2">{w.label}</span>
                        <span
                          className={cn(
                            "tabular-nums",
                            tone === "danger"
                              ? "text-danger"
                              : tone === "warn"
                                ? "font-medium text-ink"
                                : "text-ink-2",
                          )}
                        >
                          {w.usedPercent === null
                            ? "—"
                            : `${String(Math.round(used))}% used`}
                          {w.resetAt && (
                            <span className="text-ink-3">
                              {" "}
                              · resets {formatWhen(w.resetAt)}
                            </span>
                          )}
                        </span>
                      </div>
                      <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-sunken">
                        <div
                          className={cn(
                            "h-full rounded-full",
                            tone === "danger"
                              ? "bg-danger"
                              : tone === "warn"
                                ? "bg-ink"
                                : "bg-ink-3",
                          )}
                          style={{ width: `${String(Math.min(used, 100))}%` }}
                        />
                      </div>
                    </li>
                  );
                })}
              </ul>
              {l.details.length > 0 && (
                <p className="mt-3 text-xs text-ink-3">
                  {l.details.join(" · ")}
                </p>
              )}
            </Panel>
          ))}
        </ul>
      )}
    </div>
  );
}

/** How each kind of event reaches the owner. */
export function NotificationsSettings({
  rules,
}: {
  rules: NotificationRule[];
}) {
  const [values, setValues] = useState(
    Object.fromEntries(rules.map((r) => [r.event, r.delivery])),
  );
  const [status, setStatus] = useState<{
    error: string | null;
    saved: boolean;
  }>({
    error: null,
    saved: false,
  });
  const [busy, start] = useTransition();
  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <Panel as="ul" className="divide-y divide-line">
        {rules.map((r) => (
          <li
            key={r.event}
            className="flex flex-wrap items-center justify-between gap-3 px-5 py-3"
          >
            <span className="text-sm">{r.label}</span>
            <Select
              aria-label={`${r.label}: delivery`}
              value={values[r.event]}
              onChange={(e) => {
                setValues({
                  ...values,
                  [r.event]: e.target.value as typeof r.delivery,
                });
                setStatus({ error: null, saved: false });
              }}
              className="!w-40"
            >
              <option value="instant">Instant</option>
              <option value="batched">Daily digest</option>
              <option value="silent">Silent</option>
            </Select>
          </li>
        ))}
      </Panel>
      <div className="flex items-center gap-3">
        <Button
          variant="primary"
          disabled={busy}
          onClick={() => {
            start(async () => {
              const r = await saveNotifications(values);
              setStatus({ error: r.error, saved: !r.error });
            });
          }}
        >
          Save
        </Button>
        <FormStatus error={status.error} saved={status.saved} />
      </div>
      <p className="text-xs text-ink-3">
        Applies to each workspace&apos;s Telegram bot once it is connected (the
        workspace&apos;s Settings → Channels).
      </p>
    </div>
  );
}

export function ServerSettings({ status }: { status: BackupStatus }) {
  const [password, setPassword] = useState("");
  const [schedule, setSchedule] = useState(status.schedule);
  const [keep, setKeep] = useState(status.keep);
  const [note, setNote] = useState<{ error: string | null; saved: boolean }>({
    error: null,
    saved: false,
  });
  const [rehearsal, setRehearsal] = useState<Rehearsal | null>(null);
  const [busy, start] = useTransition();
  const run = (fn: () => Promise<{ error: string | null }>) => {
    setNote({ error: null, saved: false });
    start(async () => {
      const r = await fn();
      setNote({ error: r.error, saved: !r.error });
    });
  };
  const used = status.diskTotalGb - status.diskFreeGb;
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <OpsWarnings warnings={status.warnings ?? []} />
      <PanelSection>
        <h2 className="border-b border-line px-5 py-3 font-display font-semibold">
          This machine
        </h2>
        <ul className="divide-y divide-line text-sm">
          <li className="flex items-center justify-between px-5 py-3">
            Disk
            <span
              className={
                used / status.diskTotalGb > 0.9 ? "text-danger" : "text-ink-2"
              }
            >
              {status.diskFreeGb} GB free of {status.diskTotalGb} GB
            </span>
          </li>
          <li className="flex items-center justify-between px-5 py-3">
            AGOS data
            <span className="text-ink-2">{status.dataSizeMb} MB</span>
          </li>
          <li className="flex items-center justify-between px-5 py-3">
            Backups folder
            <span className="font-mono text-xs text-ink-3">
              {status.folder}
            </span>
          </li>
        </ul>
      </PanelSection>

      <PanelSection className="flex flex-col gap-4 p-5">
        <h2 className="font-display font-semibold">Backups</h2>
        <p className="text-sm text-ink-2">
          One password-protected file with every workspace (files, tasks,
          chats), the library, automations, connectors, channels and settings.
          The agents&apos; side (their conversations, memory, identity, skills
          and schedules) is Hermes&apos;s own backup, sealed in the same file.
          Provider logins are never included: you log in once on a new machine.
        </p>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Input
            type="password"
            autoComplete="new-password"
            value={password}
            placeholder={
              status.hasPassword
                ? "Password set — type to change"
                : "Backup password (10+ characters)"
            }
            onChange={(e) => {
              setPassword(e.target.value);
            }}
            className="!w-72"
          />
          <Button
            disabled={busy || password.length < 10}
            onClick={() => {
              run(async () => {
                const r = await setBackupPassword(password);
                if (!r.error) setPassword("");
                return r;
              });
            }}
          >
            Save password
          </Button>
        </div>
        <p className="text-xs text-ink-3">
          Keep this password somewhere safe (a password manager). Without it a
          backup can&apos;t be opened.
        </p>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Select
            aria-label="Backup schedule"
            value={schedule}
            onChange={(e) => {
              setSchedule(e.target.value as typeof schedule);
            }}
            className="!w-44"
          >
            <option value="daily">Every day</option>
            <option value="weekly">Every week</option>
            <option value="off">Off</option>
          </Select>
          keep the last
          <Input
            type="number"
            min={1}
            max={60}
            value={keep}
            onChange={(e) => {
              setKeep(Number(e.target.value));
            }}
            className="!w-20"
            aria-label="Backups to keep"
          />
          <Button
            disabled={busy}
            onClick={() => {
              run(() => setBackupSchedule(schedule, keep));
            }}
          >
            Save
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="primary"
            disabled={busy || !status.hasPassword}
            onClick={() => {
              run(runBackup);
            }}
          >
            {busy ? "Working…" : "Back up now"}
          </Button>
          <Button
            disabled={busy || status.files.length === 0}
            onClick={() => {
              setNote({ error: null, saved: false });
              start(async () => {
                const r = await rehearseRestore();
                setRehearsal(r.result);
                setNote({ error: r.error, saved: false });
              });
            }}
          >
            Test a restore
          </Button>
          <FormStatus error={note.error} saved={note.saved} />
        </div>
        <p className="text-sm text-ink-2">
          {status.lastBackupAt
            ? `Last backup ${formatWhen(status.lastBackupAt)} — ${status.lastBackupOk ? "OK" : `failed: ${status.lastError ?? ""}`}`
            : "No backup yet."}
          {status.lastRehearsalAt && (
            <>
              <br />
              Last restore test {formatWhen(status.lastRehearsalAt)}:{" "}
              {status.lastRehearsal}
            </>
          )}
        </p>
        {rehearsal && (
          <div
            className={cn(
              "rounded-xl border px-4 py-3 text-sm",
              rehearsal.ok
                ? "border-line-strong bg-sunken"
                : "border-danger/40 bg-danger-soft",
            )}
          >
            <p className="font-medium">{rehearsal.detail}</p>
            <p className="mt-1 text-xs text-ink-2">
              Restored into an empty temporary folder, compared with the live
              data, then removed. Your data wasn&apos;t touched.
            </p>
          </div>
        )}
        {status.files.length > 0 && (
          <ul className="divide-y divide-line rounded-xl border border-line text-sm">
            {status.files.map((f) => (
              <li key={f.name} className="flex justify-between px-4 py-2">
                <span className="font-mono text-xs">{f.name}</span>
                <span className="text-ink-3">
                  {(f.size / 1e6).toFixed(1)} MB · {formatWhen(f.createdAt)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </PanelSection>
    </div>
  );
}
