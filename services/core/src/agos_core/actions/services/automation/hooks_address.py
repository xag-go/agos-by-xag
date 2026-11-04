"""The webhooks' public address (Settings → Automations): the https address the
public relay serves a workspace's Hermes webhook routes on, kept in AGOS
(app_settings `hooks.public_url`). The owner's page and the Co-Founder's
`set_hooks_address` both write through `save_hooks_address`.

Must not: write a Hermes webhook route (actions/hooks.py does).
"""

from __future__ import annotations

from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.db.app_settings import get_setting, set_setting

__all__ = ["hooks_address", "save_hooks_address"]


def hooks_address(core: Any) -> str:
    return str(get_setting(core.db, "hooks.public_url", ""))


def save_hooks_address(core: Any, public_url: str) -> str:
    """The webhooks' public address (the owner's page and the Co-Founder's action)."""
    url = public_url.strip().rstrip("/")
    if url and not url.startswith("https://"):
        raise ActionError("The public address must start with https://")
    set_setting(core.db, "hooks.public_url", url)
    return url
