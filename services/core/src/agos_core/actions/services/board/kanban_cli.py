"""The Board's one port to Hermes's Kanban CLI: `hermes kanban ...` on the workspace's
own board, and the agos-guard plugin's board commands (`agos-bulk`, `agos-estimate`).

Split out of agos_core.actions.kanban_board (its `_cli` and `_json`).

Owns: running those commands through the Hermes Gateway, the owner's words when
Hermes refuses or doesn't answer, and reading their JSON answers.
Must not: hold a board rule, read Hermes's board database (kanban_db.py), or run any
other Hermes command.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.engine.hermes import EngineError
from agos_core.hermes_gateway import cli as hermes_cli

__all__ = [
    "answer",
    "plugin",
    "run",
    "tried",
]

log = logging.getLogger("agos.kanban_board")


def run(core: Core, workspace_id: str, *args: str) -> str:
    """`hermes kanban <args>` on the workspace's board; ActionError when Hermes refuses."""
    if core.engine is None:
        raise ActionError("The engine isn't set up yet.")
    try:
        return hermes_cli.cli(core.engine, workspace_id, "kanban", *args)
    except EngineError as error:
        # Hermes said why it refused (an empty completion, a live worker, a parent
        # not done…): the owner reads Hermes's own words, not only that it failed.
        if error.reason:
            raise ActionError(f"The board refused: {error.reason}") from error
        raise ActionError(f"The board didn't answer: {error}") from error


def tried(core: Core, workspace_id: str, *args: str, what: str = "kanban") -> bool:
    """`hermes kanban <args>` where a refusal is only logged: False when Hermes
    refused (or there is no Hermes yet). `what` names the caller in the log line."""
    if core.engine is None:
        return False
    try:
        hermes_cli.cli(core.engine, workspace_id, "kanban", *args)
    except (EngineError, OSError) as error:
        log.warning("%s %s on %s: %s", what, args[0], workspace_id, error)
        return False
    return True


def plugin(core: Core, workspace_id: str, command: str, *args: str, timeout: float) -> str:
    """One of the agos-guard plugin's board commands (`hermes agos-bulk` /
    `agos-estimate`). Hermes imports the root's plugins, so it runs walled.
    EngineError as Hermes raised it (the caller words it)."""
    assert core.engine is not None
    return hermes_cli.walled_cli(core.engine, workspace_id, command, *args, timeout=timeout)


def answer(text: str) -> Any:
    """The JSON a Kanban command printed (Hermes may print a line before it)."""
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    if start < 0:
        raise ActionError("The board gave no answer.")
    try:
        return json.loads(text[start:])
    except ValueError as error:
        raise ActionError("The board gave an answer AGOS can't read.") from error
