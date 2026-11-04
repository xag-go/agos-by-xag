import { cn } from "@/shared/ui/cn";

/** One of the workspace's labels (AGOS's row; the card's side is a block in its
 * Hermes body). `folder` groups labels. */
export type BoardLabel = {
  id: number;
  name: string;
  color: string;
  folder?: string;
};

// Whole class names, so Tailwind sees each one (the core's COLORS list).
const COLOR_CLASS: Record<string, string> = {
  gray: "bg-ink-3/15 text-ink-2",
  red: "bg-red-500/15 text-red-700 dark:text-red-300",
  orange: "bg-orange-500/15 text-orange-700 dark:text-orange-300",
  yellow: "bg-yellow-500/20 text-yellow-800 dark:text-yellow-200",
  green: "bg-green-500/15 text-green-700 dark:text-green-300",
  teal: "bg-teal-500/15 text-teal-700 dark:text-teal-300",
  blue: "bg-blue-500/15 text-blue-700 dark:text-blue-300",
  purple: "bg-purple-500/15 text-purple-700 dark:text-purple-300",
  pink: "bg-pink-500/15 text-pink-700 dark:text-pink-300",
};

export const LABEL_COLORS = Object.keys(COLOR_CLASS);

export function labelClass(color: string): string {
  return COLOR_CLASS[color] ?? (COLOR_CLASS.gray as string);
}

/** A card's labels as small chips. */
export function LabelChips({
  ids,
  labels,
}: {
  ids: number[];
  labels: BoardLabel[];
}) {
  const mine = labels.filter((l) => ids.includes(l.id));
  if (mine.length === 0) return null;
  return (
    <span className="flex flex-wrap gap-1">
      {mine.map((l) => (
        <span
          key={l.id}
          className={cn(
            "rounded-md px-1.5 py-0.5 text-xs",
            labelClass(l.color),
          )}
          title={l.folder ? `${l.folder} / ${l.name}` : l.name}
        >
          {l.name}
        </span>
      ))}
    </span>
  );
}
