import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  getChat,
  getKanban,
  getCardServices,
  getKanbanCard,
  getModelCatalog,
  getWorkspace,
  getWorkspaceSkills,
} from "@/data/queries";
import { openCardChatId } from "@/features/kanban/card-actions";
import { CardModal } from "@/features/kanban/card-modal";
import { KanbanBoardView } from "@/features/kanban/kanban-board";
import { LiveRefresh } from "@/shared/live-refresh";
import { NewCardModal } from "@/features/kanban/new-card-modal";
import { boardOnScreen } from "@/features/kanban/optimistic";
import { PendingCards } from "@/features/kanban/pending-cards";
import { ButtonLink } from "@/shared/ui/button";
import { stampOf } from "@/server/stamp";
import { PlusIcon } from "@/shared/ui/icons";

export const metadata: Metadata = { title: "Kanban" };

/** Only plain string params are accepted; anything else counts as absent. */
function param(value: string | string[] | undefined): string | undefined {
  return typeof value === "string" ? value : undefined;
}

export default async function BoardPage({
  params,
  searchParams,
}: PageProps<"/w/[id]/kanban">) {
  const { id } = await params;
  const query = await searchParams;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();

  // The Kanban's own view (filters, group-by, a saved view…) stays in the URL when
  // a card opens and closes (features/kanban/views.ts).
  const kept = new URLSearchParams();
  for (const [k, v] of Object.entries(query))
    if (typeof v === "string" && !["card", "doc", "new"].includes(k))
      kept.set(k, v);
  const boardHref = `/w/${workspace.id}/kanban${kept.size ? `?${kept.toString()}` : ""}`;
  const cardId = param(query.card);
  const openDoc = param(query.doc);
  const adding = Boolean(param(query.new));
  // Asked together: opening a card re-renders the whole page (it is a route), so
  // the Kanban and the card come in one wait, not one after the other. The model
  // list is only for the New card form.
  const [catalog, board, card, skills, services] = await Promise.all([
    adding ? getModelCatalog() : [],
    getKanban(workspace.id),
    cardId ? getKanbanCard(workspace.id, cardId) : null,
    adding ? getWorkspaceSkills(workspace.id).catch(() => []) : [],
    cardId ? getCardServices(workspace.id, cardId).catch(() => []) : [],
  ]);
  // The card's own chat with its member, shown inside the card (made once).
  let cardChatId = card?.chatId ?? null;
  // A Founder card (his own task) has no agent to chat with.
  if (card && cardChatId === null && card.member && card.member !== "founder") {
    cardChatId = await openCardChatId(workspace.id, card.id);
  }
  const cardChat =
    cardChatId === null ? null : await getChat(workspace.id, cardChatId);
  const shown = board === null ? null : boardOnScreen(board);

  return (
    // A card click shows on the Kanban and in the open card at once, while
    // Hermes's own write runs (PendingCards; W10).
    <PendingCards board={shown}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-xl text-sm text-ink-2">
          The workspace&apos;s Kanban: a card given to a member starts by
          itself.
        </p>
        <ButtonLink
          href={`${boardHref}${kept.size ? "&" : "?"}new=1`}
          scroll={false}
          variant="primary"
        >
          <PlusIcon />
          New card
        </ButtonLink>
      </div>

      {shown === null ? (
        <p className="rounded-xl bg-danger-soft px-3 py-2 text-sm text-danger">
          The Kanban isn&apos;t answering right now.
        </p>
      ) : (
        <KanbanBoardView
          workspaceId={workspace.id}
          labels={board?.labels ?? []}
          views={board?.views ?? []}
          members={board?.members ?? []}
          goals={board?.goals ?? []}
        />
      )}
      {/* Members move cards on their own: follow them while something is live.
          Without an open card the page shows only the Kanban, so a tick asks
          for the Kanban's fingerprint and re-renders only when it changed; an
          open card (its comments, runs and chat) refreshes on every tick. */}
      <LiveRefresh
        active={
          board?.cards.some((c) =>
            ["ready", "running", "review", "triage"].includes(c.status),
          ) ?? false
        }
        stampUrl={
          cardId || adding
            ? undefined
            : `/api/w/${encodeURIComponent(workspace.id)}/kanban/stamp`
        }
        stamp={stampOf(board)}
      />

      {adding && board && (
        <NewCardModal
          workspaceId={workspace.id}
          board={board}
          catalog={catalog}
          defaultModel={workspace.defaultModel}
          skills={skills.map((s) => s.name)}
          closeHref={boardHref}
        />
      )}

      {card && board && (
        <CardModal
          key={`${card.id}:${openDoc ?? ""}`}
          workspaceId={workspace.id}
          card={card}
          chat={cardChat}
          members={board.members}
          labels={board.labels ?? []}
          closeHref={boardHref}
          openDoc={openDoc}
          services={services}
        />
      )}
    </PendingCards>
  );
}
