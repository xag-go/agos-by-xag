/** The order an automation's steps really run in, as parallel levels.
 * Mirrors engine/automation_run.py: a step starts after the steps it `waits_on`
 * (keys that are not steps are ignored); a step with none of them has no parent in
 * the run, so it starts with the first level (list order does not make it wait). */
export interface LevelStep {
  key?: string | null;
  waitsOn?: string[] | null;
  kind?: string | null;
  reviews?: string | null;
}

export function stepLevels<T extends LevelStep>(steps: T[]): T[][] {
  const keys = new Set(steps.map((s) => s.key).filter((k): k is string => !!k));
  const waits = (s: T) =>
    // a review also waits on the step it reviews (engine/team_steps.py adds it)
    [
      ...(s.waitsOn ?? []),
      ...(s.kind === "review" && s.reviews ? [s.reviews] : []),
    ].filter((w) => keys.has(w) && w !== s.key);
  const levels: T[][] = [];
  const done = new Set<string>();
  let left = steps;
  while (left.length > 0) {
    const ready = left.filter((s) => waits(s).every((w) => done.has(w)));
    if (ready.length === 0) {
      levels.push(left); // a cycle: never loop, show the rest last
      break;
    }
    levels.push(ready);
    for (const s of ready) if (s.key) done.add(s.key);
    left = left.filter((s) => !ready.includes(s));
  }
  return levels;
}

export interface Who {
  agent: string | null;
  count: number;
}
type WhoStep = LevelStep & { agent?: string | null };

/** One level's members: steps of one member read once, with how many. */
function members(level: WhoStep[]): Who[] {
  const people: Who[] = [];
  for (const s of level) {
    const agent = s.agent ?? null;
    const same = people.find((p) => p.agent === agent);
    if (same) same.count += 1;
    else people.push({ agent, count: 1 });
  }
  return people;
}

/** The single member of `level` when the previous entry is that same single member. */
function sameAlone(last: Who[] | undefined, people: Who[]): Who | undefined {
  const prev = last?.length === 1 ? last[0] : undefined;
  const only = people.length === 1 ? people[0] : undefined;
  return prev && only && prev.agent === only.agent ? prev : undefined;
}

/** "Done by": one entry per level; each holds the members of that level (steps
 * of one member read once, with how many). A straight chain gives one member per
 * entry, and neighbours of the same member merge (@a ×2), as the list always did. */
export function doneBy(steps: WhoStep[]): Who[][] {
  const out: Who[][] = [];
  for (const level of stepLevels(steps)) {
    const people = members(level);
    const prev = sameAlone(out.at(-1), people);
    if (prev) prev.count += people[0]?.count ?? 0;
    else out.push(people);
  }
  return out;
}
