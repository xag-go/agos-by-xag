"""History kept: a new workspace and member start with Hermes's own
`sessions.auto_prune: false` (seeded like the time limits: only while the profile
doesn't have the key); a later change made in Hermes is never reset."""

from typing import Any

from test_agent_profiles import add_agent
from test_library import env, ws  # noqa: F401 - fixture

from agos_core.engine import config_file
from agos_core.engine.history import AUTO_PRUNE
from agos_core.engine.rules import seeded_config


def _prune(core: Any, key: str) -> Any:
    return config_file.get(config_file.read(core.engine.profile_home(key)), AUTO_PRUNE)


def test_seeded_with_the_time_limits() -> None:
    assert seeded_config()[AUTO_PRUNE] == "false"


def test_a_new_workspace_and_member_keep_their_history(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    for key in (a, f"{a}--a-writer"):
        assert _prune(core, key) in (False, "false"), key


def test_a_resync_never_resets_a_change_made_in_hermes(env: Any) -> None:  # noqa: F811
    from agos_core.actions.engine import sync_workspace

    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    for key in (a, f"{a}--a-writer"):
        core.engine._hermes(key, "config", "set", AUTO_PRUNE, "true")  # his own change
    (core.engine.profile_home(a) / ".agos-applied").unlink()
    sync_workspace(core, a)
    for key in (a, f"{a}--a-writer"):
        assert _prune(core, key) in (True, "true"), key
