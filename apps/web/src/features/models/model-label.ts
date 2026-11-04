import type { ModelSelection } from "@agos/core";
import type { CatalogProvider } from "@/data/types";

/** Hermes's level names as the owner reads them (values stay Hermes's). */
export function effortLabel(effort: string): string {
  const names: Record<string, string> = {
    standard: "Model default",
    none: "Reasoning off",
    xhigh: "Extra high",
  };
  return names[effort] ?? effort.charAt(0).toUpperCase() + effort.slice(1);
}

function lookup(selection: ModelSelection, catalog: CatalogProvider[]) {
  const provider = catalog.find((p) => p.id === selection.provider);
  const model = provider?.models.find((m) => m.id === selection.model);
  return { provider, model };
}

/** "Opus 5.5 · High · subscription" — how a model choice reads everywhere. */
export function modelLabel(
  selection: ModelSelection,
  catalog: CatalogProvider[],
): string {
  const { model } = lookup(selection, catalog);
  const mode = selection.mode === "cli" ? "subscription" : "API";
  return [
    model?.label ?? selection.model,
    effortLabel(selection.effort),
    mode,
  ].join(" · ");
}

/** The model's short name alone, as the catalog labels it (the org chart). */
export function modelName(
  selection: ModelSelection | null,
  catalog: CatalogProvider[],
): string {
  if (!selection) return "";
  const { provider, model } = lookup(selection, catalog);
  return model?.label ?? provider?.label ?? selection.model;
}
