"""The dead-man's Telegram place (deploy/agos-deadman.py, docs/error-monitoring.md).

When the core itself is down nothing in it can tell the owner, so a tiny timer
outside it (`agos-deadman.timer`, every minute) checks the core's /health and,
after 3 minutes down, sends one Telegram message straight to the Bot API.

It needs to know where to send it without asking the core. The core writes that
here, every few minutes while it runs (`<data>/system/deadman.json`, 0600):
the owner's first workspace with a Telegram bot, the path of that workspace's
Hermes `.env` (where the bot token lives: Hermes's own place for it, AGOS keeps no
copy, hermes_channel.bot_token) and the owner's Telegram id (the bot's private
chat with him). The script reads the token from that `.env` when it alerts. No
bot yet: the file is removed and the dead-man only writes to the journal.
"""

from __future__ import annotations

import contextlib
import json
import os
from typing import Any

FILE = "deadman.json"


def place(core: Any) -> dict[str, str] | None:
    """Where the dead-man sends: the first workspace with a bot and an owner id."""
    from agos_core.actions import hermes_channel, telegram_people
    from agos_core.db.workspaces import list_workspaces

    if core.engine is None:
        return None
    for workspace in list_workspaces(core.db):
        if not hermes_channel.bot_token(core, workspace.id):
            continue
        owner = telegram_people.owner_id(core, workspace.id)
        if owner:
            env_file = core.engine.profile_home(workspace.id) / ".env"
            return {"envFile": str(env_file), "chatId": owner, "workspace": workspace.name}
    return None


def write_place(core: Any) -> bool:
    """Keeps deadman.json in line; True when the dead-man has a place to send to."""
    path = core.settings.data_dir / "system" / FILE
    found = place(core)
    if found is None:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        return False
    text = json.dumps(found, indent=2)
    with contextlib.suppress(OSError):
        if path.read_text() == text:
            return True
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
    temp.replace(path)
    return True
