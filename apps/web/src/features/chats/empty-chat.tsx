"use client";

const STARTERS = [
  "What's in this workspace?",
  "Summarize what changed recently.",
  "Propose the next three tasks for the Kanban.",
];

export function EmptyChat({
  title,
  onPick,
}: {
  title: string;
  onPick: (text: string) => void;
}) {
  return (
    <div className="mx-auto flex max-w-lg flex-col items-center gap-5 pt-16 text-center">
      <span className="flex size-12 items-center justify-center rounded-2xl bg-accent font-display text-xl font-bold text-accent-ink ">
        A
      </span>
      <div>
        <p className="font-display text-xl font-semibold text-ink">{title}</p>
        <p className="mt-1.5 text-sm text-ink-2">
          Ask anything, paste a screenshot, or send a voice note. The agent
          works only inside this workspace.
        </p>
      </div>
      <div className="flex flex-wrap justify-center gap-2">
        {STARTERS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => {
              onPick(s);
            }}
            className="rounded-full border border-line bg-panel px-3.5 py-1.5 text-sm text-ink-2 hover:border-accent hover:text-ink"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
