"use client";

import type { ModelSelection, ProviderMode } from "@agos/core";
import { useState } from "react";
import type { CatalogProvider } from "@/data/types";
import { Field, Select } from "@/shared/ui/field";
import { effortLabel } from "./model-label";

const modeLabels: Record<ProviderMode, string> = {
  cli: "Subscription (CLI)",
  api: "API key",
};

/**
 * Provider → mode → model → effort. Each menu only offers what the one before
 * allows, so an impossible combination can't be picked.
 */
/**
 * The catalog plus the saved choice when Hermes no longer lists it, so opening
 * a form never switches the owner's model silently.
 */
export function withSelection(
  catalog: CatalogProvider[],
  selection: ModelSelection,
): CatalogProvider[] {
  const provider = catalog.find((p) => p.id === selection.provider);
  const listed = provider?.models.find(
    (m) => m.id === selection.model && m.modes.includes(selection.mode),
  );
  if (listed) return catalog;
  const saved = {
    id: selection.model,
    label: `${selection.model} (not listed now)`,
    modes: [selection.mode],
    efforts: [selection.effort],
    defaultEffort: selection.effort,
  };
  if (!provider)
    return [
      ...catalog,
      { id: selection.provider, label: selection.provider, models: [saved] },
    ];
  return catalog.map((p) =>
    p === provider ? { ...p, models: [saved, ...p.models] } : p,
  );
}

export function ModelPicker({
  catalog: listed,
  initial,
  name = "model",
  onChange,
  showEffort = true,
}: {
  catalog: CatalogProvider[];
  initial: ModelSelection;
  name?: string;
  /** Also told about every change (the hidden field is kept for forms). */
  onChange?: (value: ModelSelection) => void;
  /** Off where the choice has no effort of its own (a fallback model). */
  showEffort?: boolean;
}) {
  const [value, setValueState] = useState(initial);
  const setValue = (next: ModelSelection) => {
    setValueState(next);
    onChange?.(next);
  };
  const catalog = withSelection(listed, initial);

  const provider = catalog.find((p) => p.id === value.provider) ?? catalog[0];
  const modes = [...new Set(provider?.models.flatMap((m) => m.modes) ?? [])];
  const models = provider?.models.filter((m) => m.modes.includes(value.mode));
  const model = models?.find((m) => m.id === value.model) ?? models?.[0];

  function pickProvider(id: string) {
    const next = catalog.find((p) => p.id === id);
    const first = next?.models[0];
    if (!next || !first) return;
    const mode = first.modes.includes(value.mode) ? value.mode : first.modes[0];
    if (!mode) return;
    setValue({
      provider: next.id,
      mode,
      model: first.id,
      effort: first.defaultEffort,
    });
  }

  function pickMode(mode: ProviderMode) {
    const first = provider?.models.find((m) => m.modes.includes(mode));
    if (!first) return;
    const keep = provider?.models.find(
      (m) => m.id === value.model && m.modes.includes(mode),
    );
    const target = keep ?? first;
    setValue({
      ...value,
      mode,
      model: target.id,
      effort: target.efforts.includes(value.effort)
        ? value.effort
        : target.defaultEffort,
    });
  }

  function pickModel(id: string) {
    const target = models?.find((m) => m.id === id);
    if (!target) return;
    setValue({
      ...value,
      model: target.id,
      effort: target.efforts.includes(value.effort)
        ? value.effort
        : target.defaultEffort,
    });
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <Field label="Provider">
        <Select
          value={provider?.id}
          onChange={(e) => {
            pickProvider(e.target.value);
          }}
        >
          {catalog.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Connection">
        <Select
          value={value.mode}
          onChange={(e) => {
            pickMode(e.target.value as ProviderMode);
          }}
        >
          {modes.map((m) => (
            <option key={m} value={m}>
              {modeLabels[m]}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Model">
        <Select
          value={model?.id}
          onChange={(e) => {
            pickModel(e.target.value);
          }}
        >
          {models?.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
            </option>
          ))}
        </Select>
      </Field>
      {showEffort && (
        <Field label="Effort">
          <Select
            value={value.effort}
            onChange={(e) => {
              setValue({ ...value, effort: e.target.value });
            }}
            disabled={(model?.efforts.length ?? 0) < 2}
          >
            {model?.efforts.map((effort) => (
              <option key={effort} value={effort}>
                {effortLabel(effort)}
              </option>
            ))}
          </Select>
        </Field>
      )}
      <input type="hidden" name={name} value={JSON.stringify(value)} />
    </div>
  );
}
