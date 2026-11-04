export const themeCookie = "agos-theme";

export const themes = ["system", "light", "dark"] as const;
export type Theme = (typeof themes)[number];

/** Anything unexpected in the cookie counts as "system". */
export function parseTheme(value: string | undefined): Theme {
  return themes.find((t) => t === value) ?? "system";
}
