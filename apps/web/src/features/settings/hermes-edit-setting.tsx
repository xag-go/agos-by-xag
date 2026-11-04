"use client";

import { useState, useTransition } from "react";
import type { HermesSettingRow as HermesSetting } from "@/data/queries";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { useAsk } from "@/shared/ui/confirm";
import { DialogCloseButton, Modal } from "@/shared/ui/dialog";
import { Field, Input, Select, Textarea } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { saveHermesSetting } from "./hermes-settings-actions";
import {
  initialText,
  shownValue,
  type Workspace,
} from "./hermes-settings-shared";

export function EditSetting({
  row,
  workspaces,
  onClose,
}: {
  row: HermesSetting;
  workspaces: Workspace[];
  onClose: () => void;
}) {
  const [text, setText] = useState(initialText(row));
  const [on, setOn] = useState(row.value === true);
  const [scope, setScope] = useState<string>("");
  const [status, setStatus] = useState<{
    error: string | null;
    saved?: boolean;
  }>({ error: null });
  const [busy, start] = useTransition();
  const { dialog, confirm } = useAsk();

  const value = ():
    { ok: true; value: unknown } | { ok: false; error: string } => {
    switch (row.type) {
      case "boolean":
        return { ok: true, value: on };
      case "number": {
        if (text.trim() === "") return { ok: true, value: null };
        const n = Number(text);
        return Number.isFinite(n)
          ? { ok: true, value: n }
          : { ok: false, error: "Use a number." };
      }
      case "list":
      case "object":
        try {
          return { ok: true, value: JSON.parse(text) as unknown };
        } catch {
          return {
            ok: false,
            error: `Write it as JSON (e.g. ${row.type === "list" ? '["one", "two"]' : '{"name": "value"}'}).`,
          };
        }
      default:
        return { ok: true, value: text };
    }
  };

  const save = (reset: boolean, chosen?: { value: unknown }) => {
    const got = chosen ? { ok: true as const, value: chosen.value } : value();
    if (!reset && !got.ok) {
      setStatus({ error: got.error });
      return;
    }
    start(async () => {
      const result = await saveHermesSetting({
        key: row.key,
        value: reset || !got.ok ? null : got.value,
        workspaceId: scope || null,
        reset,
      });
      setStatus(result);
      if (!result.error) onClose();
    });
  };

  return (
    <Modal label={`Change ${row.key}`} onClose={onClose} size="lg">
      <div className="flex flex-col gap-4 p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h3 className="font-medium break-all">{row.key}</h3>
            <p className="mt-1 text-sm text-ink-2">{row.description}</p>
          </div>
          <DialogCloseButton />
        </div>
        {row.rule?.kind === "seeded" || row.rule?.kind === "choice" ? (
          <p className="text-sm text-ink-2">{row.rule.reason}</p>
        ) : null}
        {row.type === "boolean" ? (
          <div role="radiogroup" aria-label="Value" className="flex gap-2">
            {[
              [true, "On"],
              [false, "Off"],
            ].map(([v, label]) => (
              <label
                key={String(v)}
                className={cn(
                  "flex cursor-pointer items-center gap-2 rounded-xl border px-4 py-2 text-sm",
                  on === v ? "border-ink" : "border-line",
                )}
              >
                <input
                  type="radio"
                  name="value"
                  checked={on === v}
                  onChange={() => {
                    setOn(v as boolean);
                  }}
                />
                {label}
              </label>
            ))}
          </div>
        ) : row.type === "select" && row.options.length > 0 ? (
          <Field label="Value">
            <Select
              value={text}
              onChange={(e) => {
                setText(e.target.value);
              }}
            >
              {!row.options.includes(text) ? (
                <option value={text}>{text || "(empty)"}</option>
              ) : null}
              {row.options.map((o) => (
                <option key={o} value={o}>
                  {o || "(empty)"}
                </option>
              ))}
            </Select>
          </Field>
        ) : row.type === "list" || row.type === "object" ? (
          <Field
            label="Value (JSON)"
            hint={
              row.type === "list"
                ? 'A list, e.g. ["git push --force*", "rm -rf /*"]'
                : 'A mapping, e.g. {"anthropic": "round_robin"}'
            }
          >
            <Textarea
              value={text}
              rows={6}
              className="font-mono"
              onChange={(e) => {
                setText(e.target.value);
              }}
            />
          </Field>
        ) : (
          <Field
            label="Value"
            hint={row.type === "number" ? "Empty: not set (null)." : undefined}
          >
            <Input
              type={row.type === "number" ? "number" : "text"}
              step="any"
              value={text}
              onChange={(e) => {
                setText(e.target.value);
              }}
            />
          </Field>
        )}
        {row.source === "env" ? (
          <p className="text-xs text-ink-3">
            A line of each profile&apos;s .env, written by Hermes&apos;s own
            .env writer.
          </p>
        ) : (
          <p className="text-xs text-ink-3">
            Hermes default:{" "}
            <code className="break-all">
              {row.inDefaults ? shownValue(row.default) : "none listed"}
            </code>
          </p>
        )}
        <Field
          label="Where"
          hint="Written with Hermes's own “hermes config set” into each Co-Founder and member of the chosen workspaces."
        >
          <Select
            value={scope}
            onChange={(e) => {
              setScope(e.target.value);
            }}
          >
            <option value="">Every workspace</option>
            {workspaces.map((w) => (
              <option key={w.id} value={w.id}>
                Only {w.name}
              </option>
            ))}
          </Select>
        </Field>
        <FormStatus error={status.error} saved={status.saved} />
        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="primary"
            disabled={busy}
            onClick={() => {
              save(false);
            }}
          >
            {busy ? "Saving…" : "Save"}
          </Button>
          {row.rule?.kind === "choice" ? (
            <Button
              disabled={busy}
              onClick={() => {
                save(false, { value: row.rule?.recommended });
              }}
            >
              Use AGOS&apos;s value ({shownValue(row.rule.recommended)})
            </Button>
          ) : null}
          {row.source === "env" ? (
            <Button
              disabled={busy || row.setIn === 0}
              onClick={() => {
                void confirm({
                  title: `Remove ${row.key} from .env?`,
                  body: `Hermes's own unset removes the line ${scope ? "in this workspace" : "in every workspace"}.`,
                  confirmLabel: "Remove the line",
                }).then((yes) => {
                  if (yes) save(true);
                });
              }}
            >
              Remove the line
            </Button>
          ) : row.inDefaults ? (
            <Button
              disabled={busy || row.setIn === 0}
              onClick={() => {
                void confirm({
                  title: `Back to Hermes's default for ${row.key}?`,
                  body: `Hermes then uses ${shownValue(row.default)} ${scope ? "in this workspace" : "in every workspace"}.`,
                  confirmLabel: "Use Hermes's default",
                }).then((yes) => {
                  if (yes) save(true);
                });
              }}
            >
              Use Hermes&apos;s default
            </Button>
          ) : null}
          <Button variant="ghost" disabled={busy} onClick={onClose}>
            Cancel
          </Button>
        </div>
      </div>
      {dialog}
    </Modal>
  );
}
