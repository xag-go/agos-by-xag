"""An automation's readable file: the instructions no Hermes job holds (a Kanban or
webhook-only automation's one copy, or the owner's request Hermes refused).

Owns: writing, reading and dropping that file. Must not: talk to Hermes cron.
"""

import contextlib
import re
from pathlib import PurePosixPath
from typing import Any

from agos_core.context import Core
from agos_core.storage.layout import workspace_paths
from agos_core.storage.paths import make_roots, resolve_safe_path

__all__ = [
    "read_instructions",
]


def file_path(core: Core, workspace_id: str, file: str) -> Any:
    """Resolved inside the workspace's automations folder only."""
    folder = workspace_paths(core.layout, workspace_id).automations
    return resolve_safe_path(make_roots(write=[folder]), PurePosixPath(file).name, "write")


def write_file(core: Core, workspace_id: str, *, file: str, instructions: str) -> None:
    """The instructions only (its name, schedule, model and on/off are Hermes's job's
    or AGOS's row's, never repeated here): a Kanban automation's brief (AGOS's team
    plan), or a one-agent job's while Hermes's job doesn't hold them yet."""
    target = file_path(core, workspace_id, file)
    target.write_text(f"---\nagos: the automation's instructions\n---\n\n{instructions}\n")
    target.chmod(0o600)


_FILE = re.compile(r"\A---\n.*?\n---\n\n?(?P<body>.*)\Z", re.S)


def read_instructions(core: Core, workspace_id: str, file: str) -> str | None:
    """The instructions from the automation's file (None: there is no file)."""
    try:
        text = file_path(core, workspace_id, file).read_text()
    except (OSError, ValueError):
        return None
    match = _FILE.match(text)
    body = match["body"] if match else text
    return body.removesuffix("\n")


def drop_file(core: Core, workspace_id: str, file: str, held: str) -> None:
    """Hermes's job holds the instructions now (`held`): AGOS's file goes. A file
    that says something else was written since (the owner saved again): it stays,
    the owner's newer request, and goes into the job on its own sync."""
    if read_instructions(core, workspace_id, file) not in (None, held):
        return
    with contextlib.suppress(OSError, ValueError):
        file_path(core, workspace_id, file).unlink(missing_ok=True)
