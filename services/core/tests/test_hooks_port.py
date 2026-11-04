"""A workspace's Hermes webhook port is never one another program already holds."""

import socket
from typing import Any

from test_automations import env  # noqa: F401 - fixture

from agos_core.actions import hooks


def test_a_new_workspace_skips_a_port_already_in_use(env: Any) -> None:  # noqa: F811
    _client, core, _cron, ws = env
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
        held.bind(("127.0.0.1", 0))
        held.listen()
        busy = held.getsockname()[1]
        old = hooks.FIRST_PORT
        hooks.FIRST_PORT = busy
        try:
            from agos_core.engine import envfile

            envfile.rewrite(core.engine.profile_home(ws) / ".env", ("WEBHOOK_PORT=",), [])
            port = hooks.port_of(core, ws)
        finally:
            hooks.FIRST_PORT = old
    assert port != busy
    assert hooks.port_of(core, ws) == port  # the same from now on
    # Hermes's own setting holds it (WEBHOOK_PORT in the workspace's .env); AGOS
    # keeps no copy.
    env = (core.engine.profile_home(ws) / ".env").read_text()
    assert f"WEBHOOK_PORT={port}" in env.splitlines()
    assert (
        core.db.execute(
            "SELECT COUNT(*) FROM app_settings WHERE key LIKE 'hooks.port.%'"
        ).fetchone()[0]
        == 0
    )
