"""A workspace's gateway start in the background never dies with an unhandled thread
error: an id the engine refuses (a malformed one, as the API fuzzer sends to restore)
is logged and left, like a Hermes that can't start (integrator finding, eng/w8)."""

import threading
from typing import Any

from test_library import env  # noqa: F401 - fixture

from agos_core.actions import idle, workspaces


def test_a_refused_workspace_id_never_raises_in_the_start_thread(env: Any) -> None:  # noqa: F811
    _client, core, _runner, _home = env
    core.engine.start = lambda *_a, **_k: None
    assert idle.ensure(core, "../Bad Id!") is False
    errors: list[BaseException | None] = []
    old = threading.excepthook
    threading.excepthook = lambda args: errors.append(args.exc_value)
    try:
        workspaces._serve(core, "../Bad Id!")
        for t in threading.enumerate():
            if t.name.startswith("serve-"):
                t.join(10)
    finally:
        threading.excepthook = old
    assert errors == []
