/** A Hermes value in plain words (the whole value: nothing is cut). Used by the
 * helper-model cards, which show the raw managed value next to the choice. */
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
