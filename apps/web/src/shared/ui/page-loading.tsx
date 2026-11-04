/** Shown at once while a page loads (its data comes from the core), so a click
 * always answers right away. */
export function PageLoading() {
  return (
    <div
      role="status"
      aria-label="Loading"
      className="flex animate-pulse flex-col gap-4 motion-reduce:animate-none"
    >
      <div className="h-6 w-48 rounded-lg bg-sunken" />
      <div className="h-24 rounded-2xl bg-sunken" />
      <div className="grid gap-4 md:grid-cols-2">
        <div className="h-32 rounded-2xl bg-sunken" />
        <div className="h-32 rounded-2xl bg-sunken" />
      </div>
    </div>
  );
}
