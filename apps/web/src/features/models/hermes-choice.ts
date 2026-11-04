import type { ModelSelection } from "@agos/core";
import type { CatalogProvider } from "@/data/types";

/** The picker's choice for a Hermes provider + model (the catalog says which
 * AGOS provider and way in each Hermes provider name is: hermesProviders). */
export function asSelection(
  catalog: CatalogProvider[],
  provider: string,
  model: string,
): ModelSelection | null {
  if (!provider && !model) return null;
  for (const p of catalog) {
    const mode = Object.entries(p.hermesProviders ?? {}).find(
      ([, name]) => name === provider,
    )?.[0];
    if (mode === "cli" || mode === "api")
      return { provider: p.id, mode, model, effort: "" };
  }
  return { provider, mode: "api", model, effort: "" };
}

/** Hermes's provider name for a picker choice (the core's mapping). */
export function hermesName(
  catalog: CatalogProvider[],
  pick: ModelSelection,
): string {
  return (
    catalog.find((p) => p.id === pick.provider)?.hermesProviders?.[pick.mode] ??
    pick.provider
  );
}
