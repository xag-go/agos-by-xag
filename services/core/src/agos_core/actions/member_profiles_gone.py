"""The Hermes profiles of the people the owner once shared a workspace with, deleted.

Before AGOS became single-user (no login, migration 141), each member got his own
Hermes profile in each workspace shared with him: `agos-<workspace>--m<member id>`,
in Hermes the root's `profiles/m<id>`. Nothing reads them any more, but they still
sit in every root (and AGOS's per-profile syncs would keep writing into them). At
core start they are deleted with Hermes's own `hermes profile delete`, the way a
removed member's profile always went (engine `delete_profile`); a second start
finds none and does nothing.

Only a profile folder named exactly `m` + digits is taken. The team's agents are
`--a-<agent>` (`profiles/a-<agent>`, actions/agent_profiles.py) and never match;
the Co-Founder is the root itself, not a folder under `profiles/`.
"""

from __future__ import annotations

import logging
import re

from agos_core.context import Core
from agos_core.db import workspaces as workspaces_repo
from agos_core.engine.hermes import EngineError

log = logging.getLogger("agos.members")

MEMBER_PROFILE = re.compile(r"m\d{1,9}")


def leftovers(core: Core) -> list[str]:
    """AGOS's keys (`<workspace>--m<id>`) of the member profiles still on disk."""
    engine = core.engine
    if engine is None:
        return []
    found: list[str] = []
    for workspace_id in workspaces_repo.ids(core.db):
        if engine.migrating(workspace_id):
            continue  # its root is being moved: left for the next start
        folder = engine.root(workspace_id) / "profiles"
        if not folder.is_dir():
            continue
        found += [
            f"{workspace_id}--{p.name}"
            for p in sorted(folder.iterdir())
            if p.is_dir() and MEMBER_PROFILE.fullmatch(p.name)
        ]
    return found


def remove_all(core: Core) -> list[str]:
    """Deletes every leftover member profile; returns the keys that are gone."""
    engine = core.engine
    if engine is None:
        return []
    gone: list[str] = []
    for key in leftovers(core):
        try:
            engine.delete_profile(key)
        except (EngineError, OSError):
            log.exception("the old member profile %s was not deleted", key)
            continue
        if engine.profile_home(key).exists():
            log.warning("the old member profile %s is still there after its delete", key)
        else:
            gone.append(key)
    if gone:
        log.info("old member profiles deleted: %s", ", ".join(gone))
    return gone
