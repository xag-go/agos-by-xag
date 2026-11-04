const AREAS = [
  "task",
  "automation",
  "webhook",
  "chat",
  "cofounder",
  "goal",
  "status",
  "channel",
  "system",
] as const;
type Area = (typeof AREAS)[number];

const one = (v: string | string[] | null | undefined) =>
  typeof v === "string" ? v : undefined;

/** The Log's filters from the URL (the page and its live-refresh stamp read
 * them the same way, so both ask the core for the same entries). */
export function logFilters(
  get: (name: string) => string | string[] | null | undefined,
) {
  const level: "problems" | "all" =
    one(get("level")) === "problems" ? "problems" : "all";
  const wanted = one(get("area"));
  const area = AREAS.includes(wanted as Area) ? (wanted as Area) : undefined;
  const q = (one(get("q")) ?? "").slice(0, 200);
  // Who did it (owner, cofounder, member, member:<name>, automation[:<id>], system).
  const asked = one(get("actor")) ?? "";
  const actor = /^[a-z]{1,20}(:[A-Za-z0-9_.-]{1,64})?$/.test(asked)
    ? asked
    : "";
  const day = (v: string | undefined) =>
    v && /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : "";
  const since = day(one(get("since")));
  const until = day(one(get("until")));
  return { level, area, q, actor, since, until };
}
