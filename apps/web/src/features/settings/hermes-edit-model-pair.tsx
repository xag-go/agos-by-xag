"use client";

import { useState, useTransition } from "react";
import type { ModelSelection } from "@agos/core";
import type { HermesSettingRow as HermesSetting } from "@/data/queries";
import type { CatalogProvider } from "@/data/types";
import { firstChoice } from "@/features/models/first-choice";
import { asSelection, hermesName } from "@/features/models/hermes-choice";
import { ModelPicker } from "@/features/models/model-picker";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { useAsk } from "@/shared/ui/confirm";
import { DialogCloseButton, Modal } from "@/shared/ui/dialog";
import { Field, Select } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { saveHermesSetting } from "./hermes-settings-actions";
import { shownValue, type Workspace } from "./hermes-settings-shared";

/** A provider key and its model key, chosen together with AGOS's model picker
 * (the providers and models the workspaces really have), or left to Hermes. */
export function EditModelPair({
  pair,
  rows,
  catalog,
  workspaces,
  onClose,
}: {
  pair: { provider: string; model: string };
  rows: HermesSetting[];
  catalog: CatalogProvider[];
  workspaces: Workspace[];
  onClose: () => void;
}) {
  const providerRow = rows.find((r) => r.key === pair.provider);
  const modelRow = rows.find((r) => r.key === pair.model);
  const nowProvider =
    typeof providerRow?.value === "string" ? providerRow.value : "";
  const nowModel = typeof modelRow?.value === "string" ? modelRow.value : "";
  const hermesPicks =
    !nowModel && (nowProvider === "" || nowProvider === "auto");
  const [own, setOwn] = useState(!hermesPicks);
  const [pick, setPick] = useState<ModelSelection | null>(
    asSelection(catalog, nowProvider, nowModel) ?? firstChoice(catalog),
  );
  const [scope, setScope] = useState<string>("");
  const [status, setStatus] = useState<{
    error: string | null;
    saved?: boolean;
  }>({ error: null });
  const [busy, start] = useTransition();
  const { dialog, confirm } = useAsk();
  const parent = pair.provider.slice(0, -".provider".length);

  const save = (reset: boolean) => {
    start(async () => {
      const workspaceId = scope || null;
      if (reset) {
        for (const key of [pair.provider, pair.model]) {
          const r = await saveHermesSetting({ key, workspaceId, reset: true });
          if (r.error) {
            setStatus(r);
            return;
          }
        }
        onClose();
        return;
      }
      if (!pick) {
        setStatus({ error: "Choose a model." });
        return;
      }
      const first = await saveHermesSetting({
        key: pair.provider,
        value: hermesName(catalog, pick),
        workspaceId,
      });
      if (first.error) {
        setStatus(first);
        return;
      }
      const second = await saveHermesSetting({
        key: pair.model,
        value: pick.model,
        workspaceId,
      });
      setStatus(second);
      if (!second.error) onClose();
    });
  };

  return (
    <Modal label={`Change ${parent}`} onClose={onClose} size="lg">
      <div className="flex flex-col gap-4 p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h3 className="font-medium break-all">{parent}</h3>
            <p className="mt-1 text-sm text-ink-2">
              {providerRow?.description}
            </p>
            <p className="mt-1 text-xs text-ink-3">
              Hermes keys: <code>{pair.provider}</code> and{" "}
              <code>{pair.model}</code>. Now:{" "}
              <code className="break-all">
                {shownValue(providerRow?.value)} · {shownValue(modelRow?.value)}
              </code>
            </p>
          </div>
          <DialogCloseButton />
        </div>
        <div role="radiogroup" aria-label="Who picks" className="flex gap-2">
          {[
            [false, "Hermes picks (its own “auto”)"],
            [true, "Choose a model"],
          ].map(([v, label]) => (
            <label
              key={String(v)}
              className={cn(
                "flex cursor-pointer items-center gap-2 rounded-xl border px-4 py-2 text-sm",
                own === v ? "border-ink" : "border-line",
              )}
            >
              <input
                type="radio"
                name="who"
                checked={own === v}
                onChange={() => {
                  setOwn(v as boolean);
                }}
              />
              {label as string}
            </label>
          ))}
        </div>
        {own ? (
          pick ? (
            <ModelPicker
              name="pair-model"
              catalog={catalog}
              initial={pick}
              showEffort={false}
              onChange={setPick}
            />
          ) : (
            <p className="text-sm text-ink-2">
              No provider is signed in yet (Settings → Models).
            </p>
          )
        ) : null}
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
            disabled={busy || (own && !pick)}
            onClick={() => {
              if (own) {
                save(false);
                return;
              }
              void confirm({
                title: `Let Hermes pick for ${parent}?`,
                body: `Both keys go back to Hermes's default ${scope ? "in this workspace" : "in every workspace"}.`,
                confirmLabel: "Let Hermes pick",
              }).then((yes) => {
                if (yes) save(true);
              });
            }}
          >
            {busy ? "Saving…" : "Save"}
          </Button>
          <Button variant="ghost" disabled={busy} onClick={onClose}>
            Cancel
          </Button>
        </div>
      </div>
      {dialog}
    </Modal>
  );
}
