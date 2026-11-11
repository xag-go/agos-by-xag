"use client";

import type { ModelSelection } from "@agos/core";
import { useState, useTransition } from "react";
import type { HermesHelperModels } from "@/data/queries";
import type { CatalogProvider } from "@/data/types";
import { firstChoice } from "@/features/models/first-choice";
import { ModelPicker } from "@/features/models/model-picker";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { useAsk } from "@/shared/ui/confirm";
import { saveHermesHelperModels } from "./preferences-actions";
import { PicturesCard } from "./helper-pictures";
import {
  MAIN,
  describe,
  differences,
  stamp,
  type Confirm,
  type Task,
} from "./helper-models-shared";
import { Details, RawFields } from "./helper-fields";
import { PanelSection } from "@/shared/ui/panel";

/** Settings → Helper models: Hermes's auxiliary models (one row per task Hermes
 * has) and its image mode, as Hermes reads them. A helper's model is picked with
 * AGOS's model picker (the connected providers' models); "Same as the main model"
 * is Hermes's own `auto` (the keys removed). Saved with Hermes's own
 * `config set` / `config unset` into its managed settings (AGOS keeps no copy and
 * picks no value). Hermes's key names and raw values sit behind Details. */
export function HelperModelsPage({
  data,
  catalog,
}: {
  data: HermesHelperModels;
  catalog: CatalogProvider[];
}) {
  const { dialog, confirm } = useAsk();
  return (
    <div className="flex max-w-4xl flex-col gap-6">
      {dialog}
      <p className="text-sm text-ink-2">
        Besides the main model, Hermes uses helpers for side jobs. Each helper
        uses your main model unless you pick another one here. A choice counts
        for every workspace and member ({data.profiles} in all).
      </p>
      {data.imageMode && (
        <PicturesCard
          key={stamp([data.imageMode])}
          field={data.imageMode}
          choices={data.imageChoices}
          confirm={confirm}
        />
      )}
      <PanelSection className="p-5">
        <h3 className="font-medium">Helpers</h3>
        <p className="mt-1 text-sm text-ink-2">
          Pick the model each helper uses. The list shows the providers you are
          connected to (Settings → Models).
        </p>
        <ul className="mt-4 flex flex-col divide-y divide-line">
          {data.tasks.map((t) => (
            <HelperRow
              key={`${t.task}:${stamp(t.fields)}`}
              task={t}
              catalog={catalog}
              confirm={confirm}
            />
          ))}
        </ul>
      </PanelSection>
    </div>
  );
}

function HelperRow({
  task,
  catalog,
  confirm,
}: {
  task: Task;
  catalog: CatalogProvider[];
  confirm: Confirm;
}) {
  const route = task.route;
  const pickable = task.fields.some((f) => f.name === "provider");
  const now: ModelSelection | null =
    !route.main && route.catalogProvider && route.mode && route.model
      ? {
          provider: route.catalogProvider,
          mode: route.mode,
          model: route.model,
          effort: "",
        }
      : null;
  const [open, setOpen] = useState(false);
  const [own, setOwn] = useState(!route.main);
  const [pick, setPick] = useState<ModelSelection | null>(
    now ?? firstChoice(catalog),
  );
  const [note, setNote] = useState<string | null>(null);
  const [saving, startSave] = useTransition();
  const differ = differences(task, catalog);

  const save = () => {
    if (own && !pick) {
      setNote("Choose a model.");
      return;
    }
    if (!own && !task.fields.some((f) => f.managed)) {
      // Nothing in Hermes's shared settings to remove: say so, write nothing.
      setNote(
        route.main && differ.length === 0
          ? "It already uses the main model."
          : "Nothing to remove from Hermes's shared settings: the workspaces listed above set this in their own Hermes, and it stays there.",
      );
      return;
    }
    startSave(async () => {
      const r = await saveHermesHelperModels({}, [], {
        [task.task]: own ? pick : null,
      });
      setNote(r.error ?? "Saved in Hermes.");
      if (!r.error) setOpen(false);
    });
  };

  return (
    <li className="flex flex-col gap-2 py-4 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <span className="block text-sm font-medium">{task.label}</span>
          {task.summary && (
            <span className="block text-sm text-ink-2">{task.summary}</span>
          )}
          <span className="mt-1 block text-sm">
            <span className="text-ink-3">Uses: </span>
            <span className={cn(route.main ? "text-ink-2" : "font-medium")}>
              {route.baseUrl
                ? `${route.model || "a model"} at ${route.baseUrl}`
                : describe(catalog, route)}
            </span>
          </span>
        </div>
        {pickable && !open && (
          <Button
            className="h-8"
            onClick={() => {
              setOpen(true);
              setNote(null);
            }}
          >
            Change
          </Button>
        )}
      </div>

      {differ.length > 0 && (
        <div className="rounded-lg border border-line px-3 py-2 text-sm text-warn">
          Workspaces differ:
          <ul className="mt-0.5">
            {differ.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
          Saving here sets it the same everywhere.
        </div>
      )}

      {open && (
        <div className="flex flex-col gap-3 rounded-xl border border-line p-4">
          <div
            role="radiogroup"
            aria-label={`Model for ${task.label}`}
            className="flex flex-wrap gap-2"
          >
            {(
              [
                [false, MAIN],
                [true, "Choose a model"],
              ] as const
            ).map(([v, label]) => (
              <label
                key={label}
                className={cn(
                  "flex cursor-pointer items-center gap-2 rounded-xl border px-4 py-2 text-sm",
                  own === v ? "border-ink" : "border-line",
                )}
              >
                <input
                  type="radio"
                  name={`helper-${task.task}`}
                  checked={own === v}
                  onChange={() => {
                    setOwn(v);
                    setNote(null);
                  }}
                />
                {label}
              </label>
            ))}
          </div>
          {own &&
            (pick ? (
              <ModelPicker
                name={`helper-${task.task}`}
                catalog={catalog}
                initial={pick}
                showEffort={false}
                onChange={setPick}
              />
            ) : (
              <p className="text-sm text-ink-2">
                No provider is connected yet. Connect one in Settings → Models
                to pick its models here.
              </p>
            ))}
          {!own && (
            <p className="text-sm text-ink-2">
              The helper uses whatever model the agent itself runs on.
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="primary"
              className="h-8"
              disabled={saving || (own && !pick)}
              onClick={save}
            >
              {saving ? "Saving…" : "Save"}
            </Button>
            <Button
              className="h-8"
              disabled={saving}
              onClick={() => {
                setOpen(false);
                setOwn(!route.main);
                setPick(now ?? firstChoice(catalog));
                setNote(null);
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
      {note && (
        <span role="status" className="text-sm text-ink-2">
          {note}
        </span>
      )}

      <Details
        title={`auxiliary.${task.task}`}
        notice={
          task.inHermesList
            ? null
            : "Not in Hermes's list of helper tasks (set in Hermes; Hermes's code may read it)."
        }
        description={task.description}
      >
        <RawFields fields={task.fields} confirm={confirm} />
        {pickable && (
          <p className="text-xs text-ink-3">
            Choosing a model above removes the endpoint address and API mode set
            here, so Hermes sends the helper to the model you picked.
          </p>
        )}
      </Details>
    </li>
  );
}
