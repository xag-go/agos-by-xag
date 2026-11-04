import type { HermesSettingRow as HermesSetting } from "@/data/queries";

export type Workspace = { id: string; name: string };

/** Where each AGOS card that changes a Hermes setting lives. */
export function cardHref(
  card: string,
  workspaceId: string | null,
): string | null {
  switch (card) {
    case "time-limits":
      return "/settings/general#time-limits";
    case "limits":
      return "/settings/general#loop-detector";
    case "fallback":
      return "/settings/general#fallback-models";
    case "timezone":
      return "/settings/general#timezone";
    case "voice":
      return "/settings/general#voice-notes";
    case "access":
    case "workspace-settings":
    case "models":
      return workspaceId ? `/w/${workspaceId}/settings` : null;
    case "capabilities":
      return workspaceId ? `/w/${workspaceId}/settings/capabilities` : null;
    case "autonomy":
      return workspaceId ? `/w/${workspaceId}/settings/autonomy` : null;
    case "member-topics":
    case "telegram-people":
      return workspaceId ? `/w/${workspaceId}/settings/telegram` : null;
    case "pools":
      return "/settings/models#key-pools";
    case "helper-models":
      return "/settings/helper-models";
    case "bot":
      return workspaceId ? `/w/${workspaceId}/settings/channels` : null;
    case "keys":
      return workspaceId ? `/w/${workspaceId}/settings/keys` : null;
    default:
      return null;
  }
}

/** A Hermes value in plain words (the whole value: nothing is cut). */
export function shownValue(value: unknown): string {
  if (value === true) return "on";
  if (value === false) return "off";
  if (value === null || value === undefined) return "not set";
  if (value === "") return "empty";
  if (typeof value === "string" || typeof value === "number")
    return String(value);
  if (Array.isArray(value) && value.length === 0) return "none";
  if (
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value).length === 0
  )
    return "none";
  return JSON.stringify(value);
}

export const RULE_LABEL: Record<string, string> = {
  forced: "Set by AGOS",
  locked: "Kept by AGOS",
  card: "On an AGOS card",
  seeded: "AGOS start value",
  choice: "Your choice",
  secret: "Secret",
};

export function matches(row: HermesSetting, words: string[]): boolean {
  if (words.length === 0) return true;
  const text = [
    row.key,
    row.description,
    row.rule?.reason ?? "",
    shownValue(row.value),
  ]
    .join(" ")
    .toLowerCase();
  return words.every((w) => text.includes(w));
}

export function changedFromDefault(row: HermesSetting): boolean {
  return !row.same || JSON.stringify(row.value) !== JSON.stringify(row.default);
}

export type Show = "all" | "changed" | "agos" | "differ";

export function initialText(row: HermesSetting): string {
  if (row.type === "list" || row.type === "object")
    return JSON.stringify(
      row.value ?? (row.type === "list" ? [] : {}),
      null,
      2,
    );
  if (row.value === null || row.value === undefined) return "";
  return String(row.value);
}
