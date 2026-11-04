import {
  purgeWorkspace,
  restoreWorkspace,
  unarchiveWorkspace,
} from "@/features/workspaces/actions";
import { formatWhen } from "@/shared/format";
import { Button } from "@/shared/ui/button";
import { PanelSection } from "@/shared/ui/panel";

export function ArchiveAndTrash({
  archived,
  trashed,
  trashDays,
}: {
  archived: { id: string; name: string }[];
  trashed: { id: string; name: string; deletedAt: string }[];
  /** How long the core keeps a deleted workspace (null: not known here). */
  trashDays: number | null;
}) {
  return (
    <PanelSection className="flex flex-col gap-4 p-5">
      <h2 className="font-display font-semibold">
        Archived and deleted workspaces
      </h2>
      {archived.length === 0 && trashed.length === 0 ? (
        <p className="text-sm text-ink-3">Nothing archived or in the trash.</p>
      ) : (
        <ul className="divide-y divide-line">
          {archived.map((w) => (
            <li
              key={w.id}
              className="flex flex-wrap items-center gap-3 py-2.5 text-sm"
            >
              <span className="font-medium">{w.name}</span>
              <span className="text-ink-3">Archived</span>
              <form
                action={unarchiveWorkspace.bind(null, w.id)}
                className="ml-auto"
              >
                <Button type="submit" className="h-8">
                  Unarchive
                </Button>
              </form>
            </li>
          ))}
          {trashed.map((w) => {
            const purgeAt =
              trashDays === null
                ? null
                : new Date(
                    new Date(w.deletedAt).getTime() + trashDays * 86_400_000,
                  );
            return (
              <li
                key={w.id}
                className="flex flex-wrap items-center gap-3 py-2.5 text-sm"
              >
                <span className="font-medium">{w.name}</span>
                <span className="text-ink-3">
                  {purgeAt
                    ? `In the trash until ${formatWhen(purgeAt.toISOString())}`
                    : "In the trash"}
                </span>
                <span className="ml-auto flex gap-2">
                  <form action={restoreWorkspace.bind(null, w.id)}>
                    <Button type="submit" className="h-8">
                      Restore
                    </Button>
                  </form>
                  <form action={purgeWorkspace.bind(null, w.id)}>
                    <Button type="submit" variant="danger" className="h-8">
                      Delete now
                    </Button>
                  </form>
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </PanelSection>
  );
}
