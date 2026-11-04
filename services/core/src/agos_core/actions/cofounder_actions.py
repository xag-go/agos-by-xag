"""The Co-Founder does what the owner asks from a chat (automations, skills,
agents, MCP), through the same actions as the owner's own buttons.

Mode (Settings → General): "direct" (default, like Hermes) runs each action at
once, with Undo on its card; "ask" (and an action that is always the owner's
call, rules.needs_owner) goes through Hermes's own approval gate first: the
agos-guard plugin asks Hermes for its Allow / Deny before the agos_action tool
runs (hermes_channel.tool_check). A card AGOS makes itself (a bundle) waits for
Approve here.

This module is a compatibility facade: the code lives in actions/services/cofounder/ and
is re-exported here so every import path and patch target keeps working.
"""

from __future__ import annotations

# isort: off
from agos_core.actions.services.cofounder.chat_mode import (
    log as log,
    MODE_KEY as MODE_KEY,
    Mode as Mode,
    mode as mode,
    set_mode as set_mode,
    instructions as instructions,
    _mine as _mine,
    write_team_copies as write_team_copies,
    _existing as _existing,
)
from agos_core.actions.services.cofounder.action_cards import (
    save as save,
    _view as _view,
    of_turn as of_turn,
    _row as _row,
    _set as _set,
    _UNDO as _UNDO,
)
from agos_core.actions.services.cofounder.merges import (
    merged_lines as merged_lines,
    merged_steps as merged_steps,
    merged_reads as merged_reads,
    _changed as _changed,
)
from agos_core.actions.services.cofounder.automation_kinds import (
    automation_id_of as automation_id_of,
)
from agos_core.actions.services.cofounder.automation_kinds import (
    automation_snapshot as automation_snapshot,
)
from agos_core.actions.services.cofounder.automation_kinds import save_automation as save_automation
from agos_core.actions.services.cofounder.skill_kinds import _skill_here as _skill_here
from agos_core.actions.services.cofounder.skill_kinds import save_library_item as save_library_item
from agos_core.actions.services.cofounder.skill_kinds import _last_version as _last_version
from agos_core.actions.services.cofounder.team_kinds import (
    FILE_TYPES as FILE_TYPES,
    _team_file as _team_file,
    _file as _file,
)
from agos_core.actions.services.cofounder.dispatch import (
    _do as _do,
    _undo as _undo,
    _run as _run,
    decide as decide,
)
from agos_core.actions.services.cofounder.snapshots import (
    SNAPSHOTS_FILE as SNAPSHOTS_FILE,
    move_snapshots as move_snapshots,
)
# isort: on
