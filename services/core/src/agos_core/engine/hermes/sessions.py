"""A profile's Hermes sessions: archive or bring back, pin, rename.

Owns: Hermes's own sessions route and CLI for those three actions.

Must not: Read or store chats (db/hermes_chats.py and engine/chat.py do).

Part of engine/hermes (HermesEngine binds these functions as its methods).
"""

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from agos_core.engine.hermes.gateway_limits import API_HOST
from agos_core.engine.loop_guard import off_loop
from agos_core.hermes_gateway.errors import EngineError

log = logging.getLogger("agos.engine")

if TYPE_CHECKING:
    from agos_core.engine.hermes import HermesEngine

__all__ = [
    "archive_sessions",
    "pin_sessions",
    "rename_session",
]


def archive_sessions(
    self: "HermesEngine", home: Path, session_ids: list[str], archived: bool
) -> list[str]:
    """Hermes archives (or brings back) these sessions in that profile home; the
    ids it did. Hermes's own public route `PATCH /api/sessions/{id}` on the
    root's gateway (gateway/platforms/api_server.py _handle_patch_session: its
    SessionDB.set_session_archived); a member's under `/p/<member>/` with that
    member's own key. A session Hermes doesn't know (404) is skipped."""
    import urllib.error
    import urllib.parse
    import urllib.request

    from agos_core.engine.config_file import read_env

    if not session_ids:
        return []
    root = home.parent.parent if home.parent.name == "profiles" else home
    port = read_env(root).get("API_SERVER_PORT", "")
    key = read_env(home).get("API_SERVER_KEY", "")
    if not port.isdigit() or not key:
        raise EngineError("this workspace's engine is not set up yet")
    prefix = f"/p/{home.name}" if root != home else ""
    body = json.dumps({"archived": archived}).encode()
    done: list[str] = []
    off_loop("hermes sessions archive")
    for sid in session_ids:
        request = urllib.request.Request(
            f"http://{API_HOST}:{int(port)}{prefix}/api/sessions/"
            + urllib.parse.quote(sid, safe=""),
            data=body,
            method="PATCH",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as reply:  # noqa: S310 - loopback URL we built
                reply.read()
        except urllib.error.HTTPError as error:
            if error.code == 404:
                continue
            log.info("session %s not archived (%s)", sid, error.code)
            raise EngineError("The engine did not archive the chat") from error
        except OSError as error:
            raise EngineError("the workspace's gateway didn't answer") from error
        done.append(sid)
    return done


def pin_sessions(self: "HermesEngine", home: Path, session_ids: list[str]) -> None:
    """Hermes's own `sessions pin` in that profile home: Hermes never prunes or
    auto-archives a pinned session. Raises EngineError when one is not found
    (Hermes still pins the others)."""
    if session_ids:
        off_loop("hermes sessions pin")
        self.runner.run(
            [self.settings.hermes_bin, "sessions", "pin", *session_ids],
            timeout=120,
            env={**self._env(), "HERMES_HOME": str(home)},
        )


def rename_session(self: "HermesEngine", workspace_id: str, session_id: str, title: str) -> None:
    """Hermes's own `sessions rename` in the workspace's root."""
    self._hermes(workspace_id, "sessions", "rename", session_id, title)
