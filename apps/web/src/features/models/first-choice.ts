import type { ModelSelection } from "@agos/core";
import type { CatalogProvider } from "@/data/types";

/** The first choice the catalog really offers (its first logged-in provider's
 * first model). The core puts Hermes's own default model first in the catalog
 * (api/models.py hermes_first), so a picker starts on Hermes's model when Hermes
 * has one, else on the first model the logged-in providers offer. */
export function firstChoice(catalog: CatalogProvider[]): ModelSelection | null {
  const provider = catalog[0];
  const model = provider?.models[0];
  const mode = model?.modes[0];
  if (!provider || !model || !mode) return null;
  return {
    provider: provider.id,
    mode,
    model: model.id,
    effort: model.defaultEffort,
  };
}
