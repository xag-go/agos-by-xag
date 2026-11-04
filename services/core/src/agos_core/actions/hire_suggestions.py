"""The owner asks the Co-Founder to grow the team ("Suggest hires" on Hierarchy).

One Hermes Kanban card, assigned to the workspace's Co-Founder (its root's default
profile): it reads the goal and the team, follows its team-design skill and sends
each hire the team needs now as its OWN agos_propose (kind hire), so the owner
approves some and rejects others one by one in his Inbox. AGOS keeps no copy of the
request: the card is found again on Hermes's board by its idempotency key's prefix
(kanban_board.keyed), and while one is still open a second ask returns it instead
of making another.
"""

from __future__ import annotations

import threading
import time

from agos_core.context import Core

KEY = "agos-suggest-hires:"  # + the ask's time (ms): every ask is a new card
TITLE = "Suggest hires"
_CLOSED = frozenset({"done", "archived"})

BODY = """\
The owner wants to grow the team and asks you which hires it really needs now.

1. Load your team-design skill and follow it.
2. Read the workspace goal and its sub-goals (agos_goals, action status) and the team:
   each member's role, who reports to whom, what each one is busy with.
3. Propose the hires the team needs now, each as its OWN proposal with agos_propose,
   kind "hire", in full detail: name, title, role, reports_to, skills (only ones this
   workspace has), goal_id, why (the gap against the goal and why no member covers
   it), kit (its tools, skills, docs and examples, team context and an onboarding
   test, none of them empty: your team-design skill says how), model (the exact
   version and effort, sized to the role's work) with model_why in its own field (the
   same skill), and source_card = this card's id (your Kanban task). AGOS refuses a
   hire missing any of it and says what: fix it and propose again. One proposal per hire: the owner
   approves some and rejects others one by one in his Inbox.
4. If no hire is needed, or a change to a member's role or a reports_to move covers
   the gap, say so and propose that instead (agos_propose kind "instructions", or ask
   him to move the member in Hierarchy).
5. Then complete this card with a one-paragraph summary: what you proposed and why,
   or why the team needs no one new.
"""

_lock = threading.Lock()


def open_card(core: Core, workspace_id: str) -> str | None:
    """The owner's ask still open on Hermes's board (its newest), or None."""
    from agos_core.actions import kanban_board

    found = [c for c in kanban_board.keyed(core, workspace_id, KEY) if c["status"] not in _CLOSED]
    found.sort(key=lambda c: str(c["key"]))
    return str(found[-1]["id"]) if found else None


def ask(core: Core, workspace_id: str, note: str = "") -> tuple[str, bool]:
    """(the card, made now). A new card on the Co-Founder, the owner's note in it
    word for word; while an earlier ask is still open, that one (nothing new)."""
    from agos_core.actions import kanban_board
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    with _lock:
        waiting = open_card(core, workspace_id)
        if waiting is not None:
            return waiting, False
        said = note.strip()
        title = f"{TITLE}: {' '.join(said.split())}" if said else TITLE
        body = BODY
        if said:
            body += f"\n## The owner's note (word for word)\n\n{said}\n"
        card = kanban_board.create(
            core,
            workspace_id,
            title,
            body,
            kanban_board.COFOUNDER,
            once=f"{KEY}{time.time_ns() // 1_000_000}",
        )
        return card, True
