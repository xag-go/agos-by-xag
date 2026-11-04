"""The MCP address re-check when a root's gateway starts.

Hermes's MCP client connects from this machine. AGOS writes only checked servers
(security/mcp_address via actions/services/library/apply), but config.yaml can also
change by other paths (Hermes's own `hermes mcp add`, an edit, a restored backup) and a
name can resolve to a new address. So before the root's one gateway starts, every
profile of the root (its Co-Founder and each member) is read, and each switched-on
server that points at this computer or the local network, or that runs a command on
this machine, is switched off through Hermes's own config writer. A server the owner
added as a local command (it runs in the workspace's container, reached through AGOS's
loopback relay) stays on.

Owns: Which profile homes of a root are checked and the one `mcp_servers` write per
home that switches the refused entries off.

Must not: Decide the address rule (security/mcp_address), drop an entry (it is kept,
switched off, so the owner still sees it), or start the gateway when a refused entry
can't be switched off (the start fails instead: never connect to it).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from agos_core.engine import config_file
from agos_core.hermes_gateway.errors import EngineError
from agos_core.security import mcp_address

if TYPE_CHECKING:
    from agos_core.engine.hermes import HermesEngine

log = logging.getLogger("agos.engine")

__all__ = ["switch_off_private"]


def _keys(self: HermesEngine, workspace_id: str) -> list[str]:
    """The root's key and each member profile's key ("<ws>--<profile>")."""
    keys = [workspace_id]
    folder = self.root(workspace_id) / "profiles"
    if folder.is_dir():
        keys += sorted(
            f"{workspace_id}--{p.name}"
            for p in folder.iterdir()
            if p.is_dir() and not p.name.startswith(".") and (p / "config.yaml").is_file()
        )
    return keys


def switch_off_private(self: HermesEngine, workspace_id: str) -> list[str]:
    """Switches off every refused server in the root's profiles; returns
    "<key>:<name>" for each. Raises EngineError when one can't be switched off."""
    done: list[str] = []
    for key in _keys(self, workspace_id):
        servers: Any = config_file.read(self.profile_home(key)).get("mcp_servers")
        if not isinstance(servers, dict) or not servers:
            continue
        refused = mcp_address.refused(servers)
        if not refused:
            continue
        for name, why in sorted(refused.items()):
            log.warning("MCP server %s of %s switched off: its address %s", name, key, why)
        value = json.dumps(mcp_address.with_private_off(servers), sort_keys=True)
        try:
            self.config_writes(key, [("config", "set", "--force", "mcp_servers", value)])
        except (EngineError, OSError, ValueError) as error:
            raise EngineError(
                f"an MCP server of this workspace points at this computer and could not "
                f"be switched off ({error}): the engine is not started"
            ) from error
        done += [f"{key}:{name}" for name in sorted(refused)]
    return done
