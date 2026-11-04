"use client";

import type { ModelSelection } from "@agos/core";
import { useState, useTransition } from "react";
import { AllHermesSettingsLink } from "./hermes-settings";
import type { HermesFallback } from "@/data/queries";
import type { CatalogProvider } from "@/data/types";
import { firstChoice } from "@/features/models/first-choice";
import { ModelPicker } from "@/features/models/model-picker";
import { Button } from "@/shared/ui/button";
import { saveHermesFallback } from "./preferences-actions";
import { PanelSection } from "@/shared/ui/panel";

type Entry = HermesFallback["chain"][number];
/** A row of the list: what Hermes has, or a picker choice not saved yet. */
type Row = Entry & { picked?: ModelSelection };

function sameRoute(a: Entry, b: Entry): boolean {
  return (
    a.provider.toLowerCase() === b.provider.toLowerCase() &&
    a.model.toLowerCase() === b.model.toLowerCase() &&
    a.baseUrl === b.baseUrl
  );
}

function routeKey(e: Entry): string {
  return `${e.provider}\u0000${e.model}\u0000${e.baseUrl}`;
}

/** Hermes's provider name for a picker choice, as the core maps it (the
 * catalog's hermesProviders), so a new row reads like the saved ones. */
function hermesProvider(
  pick: ModelSelection,
  catalog: CatalogProvider[],
): string {
  return (
    catalog.find((p) => p.id === pick.provider)?.hermesProviders?.[pick.mode] ??
    pick.provider
  );
}

/** The models Hermes switches to, in order, when a profile's main model fails
 * (Hermes's own fallback_providers): read from and saved into Hermes's managed
 * settings, which every workspace reads (AGOS keeps no copy). */
export function FallbackCard({
  fallback,
  catalog,
}: {
  fallback: HermesFallback;
  catalog: CatalogProvider[];
}) {
  const [rows, setRows] = useState<Row[]>(fallback.chain);
  const [adding, setAdding] = useState<ModelSelection | null>(null);
  const [pickerKey, setPickerKey] = useState(0);
  const [note, setNote] = useState<string | null>(null);
  const [saving, startSave] = useTransition();
  const changed =
    rows.length !== fallback.chain.length ||
    rows.some((r, i) => {
      const was = fallback.chain[i];
      return !was || !sameRoute(r, was);
    });

  const providerLabel = (e: Entry): string => {
    const p = catalog.find((c) => c.id === e.catalogProvider);
    return p?.label ?? e.provider;
  };
  const modelLabel = (e: Entry): string => {
    const p = catalog.find((c) => c.id === e.catalogProvider);
    return p?.models.find((m) => m.id === e.model)?.label ?? e.model;
  };
  const connected = (e: Entry): boolean =>
    catalog.some(
      (c) =>
        c.id === e.catalogProvider &&
        c.models.some((m) => !e.mode || m.modes.includes(e.mode)),
    );

  const move = (index: number, to: number) => {
    if (to < 0 || to >= rows.length) return;
    const next = [...rows];
    const [item] = next.splice(index, 1);
    if (item !== undefined) next.splice(to, 0, item);
    setRows(next);
    setNote(null);
  };
  const remove = (index: number) => {
    setRows(rows.filter((_, i) => i !== index));
    setNote(null);
  };
  const add = () => {
    if (!adding) return;
    const row: Row = {
      provider: hermesProvider(adding, catalog),
      model: adding.model,
      baseUrl: "",
      catalogProvider: adding.provider,
      mode: adding.mode,
      picked: adding,
    };
    if (rows.some((r) => sameRoute(r, row))) {
      setNote(`${modelLabel(row)} is already in the list.`);
      return;
    }
    setRows([...rows, row]);
    setAdding(null);
    setNote(null);
  };
  const startAdding = () => {
    setAdding(firstChoice(catalog));
    setPickerKey((k) => k + 1);
    setNote(null);
  };

  const describe = (chain: Entry[]): string =>
    chain.length
      ? chain.map((e) => `${providerLabel(e)} ${modelLabel(e)}`).join(" → ")
      : "none";

  return (
    <PanelSection id="fallback-models" className="scroll-mt-6 p-5">
      <h3 className="font-medium">Fallback models</h3>
      <p className="mt-1 text-sm text-ink-2">
        When an agent&apos;s main model fails (rate limit, outage, expired
        login), Hermes switches to the first model in this list, then the next,
        for the rest of that turn; the next message tries the main model again.
        It is Hermes&apos;s own fallback list (fallback_providers): one list for
        every workspace and every member ({fallback.profiles} Hermes profiles),
        saved once into Hermes&apos;s managed settings, which they all read. New
        workspaces and members use it at once.
      </p>

      {fallback.spread.length > 0 && (
        <div className="mt-3 rounded-xl border border-line px-4 py-3 text-sm text-warn">
          <span className="block font-medium">Workspaces differ:</span>
          <ul className="mt-1 flex flex-col gap-1">
            {fallback.spread.map((s) => (
              <li key={s.profiles.join()}>
                {describe(s.chain)} in {s.profiles.join(", ")}
              </li>
            ))}
          </ul>
          <span className="mt-1 block">
            The list below is what most of them have. Saving sets it the same
            everywhere.
          </span>
        </div>
      )}

      <div className="mt-4 flex flex-col gap-4">
        {rows.length ? (
          <ol
            aria-label="Fallback order"
            className="divide-y divide-line rounded-xl border border-line"
          >
            {rows.map((row, index) => (
              <li
                key={routeKey(row)}
                className="flex items-center justify-between gap-3 px-4 py-2.5"
              >
                <span className="flex min-w-0 items-start gap-3 text-sm">
                  <span className="w-4 shrink-0 text-right text-ink-3 tabular-nums">
                    {index + 1}
                  </span>
                  <span className="min-w-0">
                    <span className="block font-medium">{modelLabel(row)}</span>
                    <span className="block text-ink-2">
                      {providerLabel(row)}
                      {row.mode === "cli" && " · subscription"}
                      {row.mode === "api" &&
                        row.catalogProvider !== null &&
                        " · API key"}
                    </span>
                    <span className="block font-mono text-xs break-all text-ink-3">
                      {row.provider} · {row.model}
                      {row.baseUrl && ` · ${row.baseUrl}`}
                    </span>
                    {!connected(row) && (
                      <span className="block text-xs text-warn">
                        {row.catalogProvider === null
                          ? "Set in Hermes itself (kept as it is)."
                          : "Not among the providers you're connected to: Hermes skips it until it has a login or key."}
                      </span>
                    )}
                  </span>
                </span>
                <span className="flex shrink-0 gap-1">
                  <Button
                    className="h-8 w-8 !px-0"
                    aria-label={`Move ${modelLabel(row)} up`}
                    disabled={index === 0}
                    onClick={() => move(index, index - 1)}
                  >
                    ↑
                  </Button>
                  <Button
                    className="h-8 w-8 !px-0"
                    aria-label={`Move ${modelLabel(row)} down`}
                    disabled={index === rows.length - 1}
                    onClick={() => move(index, index + 1)}
                  >
                    ↓
                  </Button>
                  <Button
                    className="h-8"
                    aria-label={`Remove ${modelLabel(row)}`}
                    onClick={() => remove(index)}
                  >
                    Remove
                  </Button>
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="rounded-xl border border-dashed border-line px-4 py-3 text-sm text-ink-2">
            No fallback models: when the main model fails, the agent stops with
            the error.
          </p>
        )}

        {adding ? (
          <div className="flex flex-col gap-3 rounded-xl border border-line p-4">
            <span className="text-sm font-medium">Add a fallback model</span>
            <ModelPicker
              key={pickerKey}
              catalog={catalog}
              initial={adding}
              name="fallback-model"
              showEffort={false}
              onChange={setAdding}
            />
            <div className="flex gap-2">
              <Button variant="primary" onClick={add}>
                Add to the list
              </Button>
              <Button onClick={() => setAdding(null)}>Cancel</Button>
            </div>
          </div>
        ) : catalog.length ? (
          <div>
            <Button onClick={startAdding}>Add a fallback model</Button>
          </div>
        ) : (
          <p className="text-sm text-ink-2">
            Connect a provider in Settings → Models to pick fallback models from
            it.
          </p>
        )}

        <div className="flex items-center gap-3">
          <Button
            variant="primary"
            disabled={saving || (!changed && !fallback.spread.length)}
            onClick={() => {
              setNote(null);
              startSave(async () => {
                const r = await saveHermesFallback(
                  rows.map((row) =>
                    row.picked
                      ? {
                          provider: row.picked.provider,
                          mode: row.picked.mode,
                          model: row.picked.model,
                        }
                      : {
                          provider: row.provider,
                          model: row.model,
                          baseUrl: row.baseUrl,
                        },
                  ),
                );
                setNote(r.error ?? "Saved in Hermes.");
              });
            }}
          >
            Save
          </Button>
          {changed && (
            <Button
              disabled={saving}
              onClick={() => {
                setRows(fallback.chain);
                setNote(null);
              }}
            >
              Undo changes
            </Button>
          )}
          {note && (
            <span role="status" className="text-sm text-ink-2">
              {note}
            </span>
          )}
        </div>
      </div>
      <AllHermesSettingsLink search="fallback" />
    </PanelSection>
  );
}
