import { cn } from "@/shared/ui/cn";

/**
 * The AGOS logo ("Orbit"): the Co-Founder in the middle, its agents on an orbit
 * around it. One geometry for every size; the orbit is cut around each agent
 * with a mask so the mark sits on any background.
 */

const AGENTS: ReadonlyArray<readonly [number, number]> = [
  [41.5, 15.55],
  [41.5, 48.45],
  [13, 32],
];

function MarkShapes({ id, color }: { id: string; color: string }) {
  return (
    <>
      <defs>
        <mask
          id={id}
          maskUnits="userSpaceOnUse"
          x="0"
          y="0"
          width="64"
          height="64"
        >
          <rect width="64" height="64" fill="#fff" />
          {AGENTS.map(([x, y]) => (
            <circle key={`${x}-${y}`} cx={x} cy={y} r="8.5" fill="#000" />
          ))}
        </mask>
      </defs>
      <circle
        cx="32"
        cy="32"
        r="19"
        fill="none"
        stroke={color}
        strokeWidth="3"
        opacity="0.45"
        mask={`url(#${id})`}
      />
      <circle cx="32" cy="32" r="9" fill={color} />
      {AGENTS.map(([x, y]) => (
        <circle key={`${x}-${y}`} cx={x} cy={y} r="5.5" fill={color} />
      ))}
    </>
  );
}

/** The bare mark in the accent colour (sidebar, headers). */
export function AgosMark({
  className,
  id = "agos-mark",
}: {
  className?: string;
  id?: string;
}) {
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden="true">
      <MarkShapes id={id} color="var(--accent)" />
    </svg>
  );
}

/** The small "AGOS by XAG" line set under the logo (rail, empty home). */
export function AgosByline({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "text-8 leading-none font-medium tracking-wide whitespace-nowrap text-ink-3",
        className,
      )}
    >
      AGOS by XAG
    </span>
  );
}
