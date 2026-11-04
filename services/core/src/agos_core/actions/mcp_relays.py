"""Local MCP servers' relays on 127.0.0.1 (engine/mcp_runner.py), with their bearer.

Each local server (a command run in the workspace's own container) and the Google
server are reached by Hermes at http://127.0.0.1:<port>/mcp through a relay. The
relay lets a connection through only with its own bearer token: Hermes's config
sends `Authorization: Bearer ${AGOS_MCP__RELAY_<NAME>}` and the token is in the
profile's .env (0600, with the other MCP keys), so another workspace's Hermes, a
DNS-rebinding MCP URL or any local process gets 401. The token is
HMAC(AGOS's internal token, "mcp-relay:<profile>:<name>"): stable across restarts,
different for every relay, never written in argv or config.yaml.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from agos_core.actions import hermes_config as hc
from agos_core.context import Core
from agos_core.engine import library as lib
from agos_core.engine.hermes import EngineError

log = logging.getLogger("agos.library")

RELAY = "_relay_"  # its key's name in the profile's .env: AGOS_MCP__RELAY_<NAME>


def token(core: Core, workspace_id: str, name: str) -> str:
    from agos_core.engine import mcp_runner

    assert core.engine is not None
    return mcp_runner.relay_token(core.internal_token, core.engine.profile(workspace_id), name)


def header(name: str) -> dict[str, str]:
    """The Hermes entry's header: the token by its .env name, never its value."""
    return {"Authorization": f"Bearer ${{{lib.env_name(RELAY + name)}}}"}


def with_google_header(servers: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The Google server's entry (apps.profile_servers) gets its relay's header too."""
    from agos_core.actions import apps
    from agos_core.engine import apps as eng

    entry = servers.get(eng.server_name(apps.GOOGLE_SERVER))
    if entry is not None:
        entry["headers"] = header(apps.GOOGLE_SERVER)
    return servers


def secrets(core: Core, workspace_id: str, here: hc.Here) -> dict[str, str]:
    """The relays' tokens, for the profile's .env (every local server that is on, and
    the Google server's)."""
    from agos_core.actions import apps

    if core.engine is None:
        return {}
    names = [
        name
        for name, entry in here.mcp.items()
        if hc.is_on(entry) and lib.is_local(hc.definition_of(entry))
    ]
    if apps.google_server(core, workspace_id, here.apps):
        names.append(apps.GOOGLE_SERVER)
    return {RELAY + name: token(core, workspace_id, name) for name in names}


def local_servers(core: Core, workspace_id: str, here: hc.Here) -> dict[str, str]:
    """Starts a container for each local MCP server that is on in this workspace,
    removes the ones that are off. Returns {name: URL}. A server that can't start
    is left out (its tools aren't given) and the problem is logged."""
    engine = core.engine
    if engine is None:
        return {}
    from agos_core.engine import mcp_runner
    from agos_core.storage.layout import workspace_paths

    profile = engine.profile(workspace_id)
    wanted = [
        (name, hc.definition_of(entry))
        for name, entry in sorted(here.mcp.items())
        if hc.is_on(entry) and lib.is_local(hc.definition_of(entry))
    ]
    urls: dict[str, str] = {}
    if wanted and engine.egress:
        engine.ensure_network(workspace_id)
    for name, definition in wanted:
        try:
            urls[name] = mcp_runner.ensure(
                engine._docker,
                profile=profile,
                name=name,
                command=str(definition["command"]),
                files_dir=workspace_paths(core.layout, workspace_id).files,
                image=engine.settings.sandbox_image,
                zone=engine.owner_zone(),
                env_key=str(definition.get("env_key") or ""),
                secret=here.keys.get(name),
                token=token(core, workspace_id, name),
            )
        except (EngineError, ValueError, OSError, IndexError) as error:
            log.error("local MCP %s of %s did not start: %s", name, workspace_id, error)
    keep = {name for name, _ in wanted}
    from agos_core.actions import apps

    if google := apps.google_server(core, workspace_id, here.apps):
        keep.add(apps.GOOGLE_SERVER)
        if engine.egress:
            engine.ensure_network(workspace_id)
        try:
            urls[apps.GOOGLE_SERVER] = mcp_runner.ensure(
                engine._docker,
                profile=profile,
                name=apps.GOOGLE_SERVER,
                command=google[0],
                files_dir=workspace_paths(core.layout, workspace_id).files,
                image=engine.settings.sandbox_image,
                zone=engine.owner_zone(),
                env_key="AGOS_GOOGLE",
                secret=google[1],
                token=token(core, workspace_id, apps.GOOGLE_SERVER),
            )
        except (EngineError, ValueError, OSError, IndexError) as error:
            log.error("Google MCP of %s did not start: %s", workspace_id, error)
    with contextlib.suppress(EngineError):
        for name in mcp_runner.running_names(engine._docker, profile) - keep:
            mcp_runner.remove(engine._docker, profile, name)
    return urls
