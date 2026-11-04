"""Sharing a workspace's MCP servers as owner templates, without their credentials.
Must not: copy a credential into a template, or touch a workspace's Hermes.

Split out of agos_core.actions.library (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import re
from typing import Any

from agos_core.actions import hermes_config as hc
from agos_core.actions.errors import ActionError
from agos_core.actions.services.library.records import TEMPLATE, is_template, log
from agos_core.context import Core
from agos_core.db import library as repo
from agos_core.engine import library as lib
from agos_core.engine.library import LibraryError

__all__ = [
    "share_servers",
]

# What looks like a credential in a server's address or command: such a server stays
# its workspace's own (never shown in Settings or offered to another workspace).
_SECRET_PARAM = re.compile(r"(?i)(key|token|secret|passw|auth|sig|session|cred)")
_SECRET_ARG = re.compile(
    r"(?i)(--?(api[-_]?key|token|secret|password|pat|auth)\b|\b[A-Z0-9_]*(KEY|TOKEN|SECRET|PASSWORD)=)"
)
_LONG_TOKEN = re.compile(r"[A-Za-z0-9_\-]{32,}")


def _shareable(definition: dict[str, Any]) -> dict[str, Any] | None:
    """The definition another workspace may see (no credential in it), or None."""
    try:
        clean = lib.check_mcp(definition, resolve=False)
    except LibraryError:
        return None
    if lib.is_local(clean):
        command = str(clean["command"])
        if _SECRET_ARG.search(command) or _LONG_TOKEN.search(command):
            return None
        return clean
    from urllib.parse import parse_qsl, urlsplit

    parts = urlsplit(str(clean["url"]))
    if any(_SECRET_PARAM.search(k) for k, _v in parse_qsl(parts.query, keep_blank_values=True)):
        return None
    if _LONG_TOKEN.search(parts.path + "?" + parts.query) or parts.fragment:
        return None
    return clean


def _free_name(core: Core, name: str) -> str:
    for n in range(2, 100):
        candidate = f"{name[:58]}-{n}"
        if repo.find_item(core.db, "mcp", candidate, None) is None:
            return candidate
    raise ActionError("Too many shared servers with this name.")


def share_servers(core: Core) -> int:
    """Every MCP server a workspace added itself (its own form, or `hermes mcp add`)
    joins Settings → Connectors → Your MCP servers: its definition only, never its
    key or sign-in. The workspace's server becomes that shared one's copy, so it
    keeps everything it had. Apps and Hermes's catalog servers are listed apart."""
    from agos_core.engine.apps import SERVER_PREFIX

    rows = repo.own_servers(core.db)
    made = 0
    for row in rows:
        ws, name = str(row["workspace_id"]), str(row["name"])
        if name.startswith(SERVER_PREFIX) or not hc.has_root(core, ws):
            continue
        entry = hc.here(core, ws).mcp.get(name)
        clean = _shareable(hc.definition_of(entry)) if entry is not None else None
        if clean is None:
            continue
        same = repo.find_item(core.db, "mcp", name, None)
        if same is not None and is_template(same) and repo.definition(same) == clean:
            shared_id = int(same["id"])
        else:
            shared_id = repo.insert_item(
                core.db,
                kind="mcp",
                name=name if same is None else _free_name(core, name),
                title=str(row["title"]),
                summary=str(row["summary"]),
                definition=clean,
                source=TEMPLATE,
            )
        repo.set_source(core.db, int(row["id"]), f"{TEMPLATE}:{shared_id}")
        log.info("MCP server %s of %s shared as #%d", name, ws, shared_id)
        made += 1
    return made
