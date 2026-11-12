import type { HermesHelperModels } from "@/data/queries";
import type { CatalogProvider } from "@/data/types";
import type { useAsk } from "@/shared/ui/confirm";

export type Task = HermesHelperModels["tasks"][number];
export type Field = Task["fields"][number];
type Route = Task["route"];
export type Choice = HermesHelperModels["imageChoices"][number];
export type Confirm = ReturnType<typeof useAsk>["confirm"];

export const MAIN = "Same as the main model";

/** Hermes's field names in plain words (shown in Details, beside the key). */
export const NAMES: Record<string, string> = {
  provider: "Provider",
  model: "Model",
  base_url: "Endpoint address",
  api_mode: "API mode",
  image_input_mode: "How pictures reach the model",
};

/** A value as the text box holds it ("" for an empty or missing value). */
export function asText(value: unknown): string {
  if (value === null || value === undefined) return "";
  return typeof value === "string" ? value : JSON.stringify(value);
}

/** Changes when Hermes's values do, so a row starts again from them. */
export function stamp(fields: Field[]): string {
  return fields.map((f) => `${f.key}=${asText(f.value)}`).join("|");
}

export function where(f: Field): string {
  if (f.spread.length > 0) return "workspaces differ";
  if (f.isDefault) return "the default";
  return f.managed
    ? "set for every workspace"
    : "set in the workspaces themselves";
}

/** "GPT 5.4 Mini (OpenAI)" for a provider + model, as the picker names them. */
export function describe(
  catalog: CatalogProvider[],
  route: Pick<Route, "main" | "provider" | "model" | "catalogProvider">,
): string {
  if (route.main) return MAIN;
  const p = catalog.find((c) => c.id === route.catalogProvider);
  const model = p?.models.find((m) => m.id === route.model)?.label;
  const provider = p?.label ?? route.provider;
  if (!route.model) return `${provider}'s default helper model`;
  return `${model ?? route.model}${provider && provider !== "auto" ? ` (${provider})` : ""}`;
}

/** Workspaces whose Hermes reads another provider/model, in plain words. */
export function differences(task: Task, catalog: CatalogProvider[]): string[] {
  const provider = task.fields.find((f) => f.name === "provider");
  const model = task.fields.find((f) => f.name === "model");
  const base = task.fields.find((f) => f.name === "base_url");
  const spreads = [provider, model, base].filter(
    (f): f is Field => f !== undefined && f.spread.length > 0,
  );
  if (spreads.length === 0) return [];
  const per = new Map<string, Record<string, string>>();
  for (const f of spreads)
    for (const s of f.spread)
      for (const who of s.profiles)
        per.set(who, { ...per.get(who), [f.name]: asText(s.value) });
  const groups = new Map<string, string[]>();
  for (const [who, got] of per) {
    const p = got.provider ?? asText(provider?.value);
    const m = got.model ?? asText(model?.value);
    const b = got.base_url ?? asText(base?.value);
    const main = (p === "" || p === "auto") && (m === "" || m === "auto") && !b;
    const p2 = catalog.find((c) =>
      Object.values(c.hermesProviders ?? {}).includes(p),
    );
    const said = b
      ? `${m || "a model"} at ${b}`
      : describe(catalog, {
          main,
          provider: p,
          model: m,
          catalogProvider: p2?.id ?? null,
        });
    groups.set(said, [...(groups.get(said) ?? []), who]);
  }
  return [...groups].map(([said, who]) => `${who.join(", ")}: ${said}`);
}
