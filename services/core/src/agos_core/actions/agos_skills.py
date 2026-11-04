"""AGOS's own Hermes skills: ONE shared folder every workspace root and team member
reads (Hermes's `skills.external_dirs`, read-only; never a per-profile copy).

- `task`: Hermes's skill command `/task <what>` (in AGOS and in Telegram): the agent
  puts it on the workspace's Kanban as one card with Hermes's own kanban_create
  (Hermes then follows the card in that conversation). AGOS no longer catches /task.
- `cofounder-actions`: the Co-Founder's agos_action kinds for the rest of the owner's
  pages, with their fields (engine/cofounder_parity/). Its prompt names each domain
  in one line; the fields are read with skill_view only when needed, so they cost no
  tokens on the turns that don't use them.
"""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from pathlib import Path

from agos_core.context import Core

log = logging.getLogger("agos.agos_skills")

TASK = """\
---
name: task
description: "Use when the owner types /task followed by what he wants done: put that on this workspace's Kanban as one card."
---

# /task: one card on the Kanban

The owner typed `/task` and then what he wants done. Put exactly that on this
workspace's Kanban as ONE card, with your kanban_create tool:

- title: a short, clear title from his words, in his language;
- body: his words as he wrote them (and how to check it is done, if he said so);
- assignee (Hermes needs one): the team member he named (its profile, a-<name>);
  else the member whose role fits the work best; else yourself (`default`).

Don't ask again and don't start the work yourself. Answer in one line with the
card's id (for example "On the Kanban as t_ab12cd34."). If nothing follows /task,
ask him in one line what the card should be.
"""


def _skills() -> dict[str, str]:
    from agos_core.engine import cofounder_parity

    return {"task": TASK, "cofounder-actions": cofounder_parity.skill_text()}


SKILLS = _skills()


def skills_dir(core: Core) -> Path:
    return core.layout.root / "agos-skills"


def ensure(core: Core) -> Path:
    """The shared folder, as this AGOS has it (written again only when it differs)."""
    folder = skills_dir(core)
    for name, text in SKILLS.items():
        path = folder / name / "SKILL.md"
        with contextlib.suppress(OSError):
            if path.is_file() and path.read_text(encoding="utf-8") == text:
                continue
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".SKILL.md.")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            Path(tmp).chmod(0o644)
            Path(tmp).replace(path)
        except OSError:
            log.exception("AGOS skill %s not written", name)
    return folder
