/** Lines the owner should act on (no backup password, backups failing), in the
 * same look as the usage-limit warnings (limit-warnings.tsx). */
export function OpsWarnings({ warnings }: { warnings: string[] }) {
  return (
    <>
      {warnings.map((text) => (
        <p
          key={text}
          role="alert"
          className="flex flex-wrap items-center gap-x-2 rounded-xl border border-ink bg-panel px-4 py-3 text-sm text-ink"
        >
          <span
            aria-hidden="true"
            className="grid size-5 place-items-center rounded-full bg-ink text-11 font-bold text-paper"
          >
            !
          </span>
          {text}
        </p>
      ))}
    </>
  );
}
