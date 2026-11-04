"""The rest of the owner's pages as the Co-Founder's chat actions (engine/
cofounder_parity/): automations' rules and heartbeats, the team's groups and kits,
Skill Studio and the Library, the board's labels, views and status cards, the Vision's
rhythm and notes, docs and agents' history, owner rules and Brain methods, keys,
apps, Telegram, templates, artifacts, the General and workspace settings, backups and
Hermes's update.

Each kind calls the same AGOS action as the owner's page (no copy of its logic) and
returns what its card's Undo needs (`before`), or what came of it (`report`).
actions/cofounder_actions.py stores the card, runs `do` and, on Undo, `undo`. A kind
whose gate is "owner" waits for his yes first (engine/cofounder_actions.needs_owner).
Everything stays in the Co-Founder's own workspace: names are looked up in it, and a
thing of another workspace is "not found".

This module is a compatibility facade: the code lives in actions/services/cofounder/ and
is re-exported here so every import path and patch target keeps working.
"""

from __future__ import annotations

# isort: off
from agos_core.actions.services.cofounder.board_actions import (
    _status_args as _status_args,
)
from agos_core.actions.services.cofounder.page_actions import (
    Do as Do,
    Undo as Undo,
    DOES as DOES,
    UNDOES as UNDOES,
    KINDS as KINDS,
    do as do,
    undo as undo,
)
from agos_core.actions.services.cofounder.automation_actions import (
    _rule as _rule,
)
from agos_core.actions.services.cofounder.action_args import Fields as Fields, Result as Result
# isort: on
