"use client";

import { type ReactNode, useState, useTransition } from "react";
import { Button } from "@/shared/ui/button";
import { shownValue } from "./hermes-settings-shared";
import { saveHermesHelperModels } from "./preferences-actions";
import {
  NAMES,
  asText,
  type Confirm,
  type Field,
  where,
} from "./helper-models-shared";

/** Hermes's own names and words, folded away. */
export function Details({
  title,
  notice = null,
  description,
  children,
}: {
  title: string;
  notice?: string | null;
  description: string;
  children: ReactNode;
}) {
  return (
    <details className="group mt-1 text-sm">
      <summary className="cursor-pointer text-xs text-ink-3 select-none hover:text-ink-2">
        Details
      </summary>
      <div className="mt-2 flex flex-col gap-3 rounded-lg bg-sunken p-3">
        <p className="font-mono text-xs break-all text-ink-3">
          Setting: {title}
        </p>
        {notice && <p className="text-xs text-warn">{notice}</p>}
        {description && (
          <p className="text-xs text-ink-2">From the engine: {description}</p>
        )}
        {children}
      </div>
    </details>
  );
}

/** Hermes's raw fields of a task (provider, model, endpoint address, API mode)
 * as text, for what the picker can't express (e.g. a custom endpoint). */
export function RawFields({
  fields,
  confirm,
  resetOnly = false,
}: {
  fields: Field[];
  confirm: Confirm;
  resetOnly?: boolean;
}) {
  const start = Object.fromEntries(fields.map((f) => [f.key, asText(f.value)]));
  const [drafts, setDrafts] = useState(start);
  const [note, setNote] = useState<string | null>(null);
  const [saving, startSave] = useTransition();
  const editable = fields.filter((f) => !f.secret);
  const changed = editable.filter((f) => drafts[f.key] !== start[f.key]);
  const pinned = editable.filter((f) => f.managed);

  const send = (sets: Record<string, string>, unsets: string[]) =>
    startSave(async () => {
      const r = await saveHermesHelperModels(sets, unsets);
      setNote(r.error ?? "Saved.");
    });

  return (
    <div className="flex flex-col gap-3">
      {!resetOnly && (
        <div className="grid gap-3 sm:grid-cols-2">
          {fields.map((f) => (
            <label key={f.key} className="flex flex-col gap-1 text-xs">
              <span>
                {NAMES[f.name] ?? f.name}{" "}
                <span className="font-mono text-ink-3">{f.key}</span>
              </span>
              {f.options.length > 0 ? (
                <select
                  value={drafts[f.key] ?? ""}
                  disabled={saving || f.secret}
                  onChange={(e) => {
                    setDrafts({ ...drafts, [f.key]: e.target.value });
                    setNote(null);
                  }}
                  className="h-8 rounded-lg border border-line bg-panel px-2 text-sm"
                >
                  {!f.options.includes(start[f.key] ?? "") && (
                    <option value={start[f.key]}>{start[f.key]}</option>
                  )}
                  {f.options.map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  value={drafts[f.key] ?? ""}
                  disabled={saving || f.secret}
                  placeholder={asText(f.hermesDefault) || "empty (the default)"}
                  onChange={(e) => {
                    setDrafts({ ...drafts, [f.key]: e.target.value });
                    setNote(null);
                  }}
                  className="h-8 rounded-lg border border-line bg-panel px-2 text-sm disabled:opacity-60"
                />
              )}
              <span className="text-ink-2">
                In use: {shownValue(f.value)} · {where(f)}
                {!f.isDefault &&
                  ` · the default: ${shownValue(f.hermesDefault)}`}
              </span>
            </label>
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {!resetOnly && (
          <Button
            className="h-7 text-xs"
            disabled={saving || changed.length === 0}
            onClick={() => {
              const sets: Record<string, string> = {};
              const unsets: string[] = [];
              for (const f of changed) {
                const v = (drafts[f.key] ?? "").trim();
                if (v) sets[f.key] = v;
                else if (f.managed) unsets.push(f.key);
              }
              if (!Object.keys(sets).length && !unsets.length) {
                setNote("Nothing changed.");
                return;
              }
              send(sets, unsets);
            }}
          >
            Save these values
          </Button>
        )}
        <Button
          className="h-7 text-xs"
          disabled={saving || pinned.length === 0}
          onClick={() => {
            void (async () => {
              const ok = await confirm({
                title: "Use the default?",
                body: `Removes ${pinned.map((f) => f.key).join(", ")} from the shared settings, so the default applies again.`,
                confirmLabel: "Use the default",
              });
              if (ok)
                send(
                  {},
                  pinned.map((f) => f.key),
                );
            })();
          }}
        >
          Use the default
        </Button>
        {note && <span className="text-xs text-ink-2">{note}</span>}
      </div>
    </div>
  );
}
