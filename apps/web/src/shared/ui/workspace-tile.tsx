/** What fills a workspace's tile: its picture when it has one (the core's
 * icon, through /api/w/<id>/icon; the `icon` stamp after `?v=` makes a new
 * picture a new address), else the first letter of its name. The tile around
 * it (size, radius, colour, transitions) stays the caller's. */
export function WorkspaceTile({
  workspace,
}: {
  workspace: { id: string; name: string; icon?: string | null };
}) {
  if (workspace.icon) {
    return (
      // eslint-disable-next-line @next/next/no-img-element -- private, same-origin file
      <img
        src={`/api/w/${encodeURIComponent(workspace.id)}/icon?v=${encodeURIComponent(workspace.icon)}`}
        alt=""
        draggable={false}
        className="size-full object-cover"
      />
    );
  }
  return <>{workspace.name.trim().charAt(0) || "?"}</>;
}
