import { doneBy, type LevelStep } from "./step-levels";

/** The "Done by" badges of a team automation: its levels in run order (→), the
 * members of one level side by side in brackets (they work at the same time). */
export function DoneByLevels({
  steps,
  titleOf,
}: {
  steps: (LevelStep & { agent?: string | null })[];
  titleOf: (name: string | null | undefined) => string;
}) {
  return doneBy(steps).map((level, i) => (
    <span key={i} className="flex items-center gap-1">
      {i > 0 && <span className="text-ink-3">→</span>}
      {level.length > 1 && (
        <span className="text-ink-3" title="These work at the same time">
          (
        </span>
      )}
      {level.map(({ agent, count }, j) => (
        <span key={j} className="flex items-center gap-1">
          {j > 0 && <span className="text-ink-3">+</span>}
          <span className="rounded-full bg-sunken px-2 py-0.5">
            {titleOf(agent)}
            {count > 1 && <span className="text-ink-3"> ×{count}</span>}
          </span>
        </span>
      ))}
      {level.length > 1 && <span className="text-ink-3">)</span>}
    </span>
  ));
}
