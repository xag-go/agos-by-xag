"""`hooks.output_spill.max_chars` is Hermes's again (area3 W1): AGOS forced it to
1,000,000 because "the plugin hands its rules to every turn as hook context". The
rules are two system-prompt sections now (bridge.py register_system_prompt_section)
and the plugin's only hook context is the clock line (~40 characters, clock.py), so
Hermes's default (10,000: H: tools/hook_output_spill.py:24) and its spill
protection for every plugin's hook context (H: agent/turn_context.py:823-835)
apply. The old forced value leaves each profile once."""

from typing import Any

from test_library import env, ws  # noqa: F401 - fixture

from agos_core.actions import hermes_all_settings as hall
from agos_core.actions import library
from agos_core.engine import config_file

KEY = "hooks.output_spill.max_chars"


def test_agos_no_longer_forces_it() -> None:
    assert KEY not in library.profile_settings([])
    assert KEY not in hall.FORCED_WHY


def test_the_old_forced_value_leaves_each_profile_once(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    home = core.engine.profile_home(a)
    core.engine._hermes(a, "config", "set", KEY, "1000000")
    assert str(config_file.get(config_file.read(home), KEY)) == "1000000"
    # (The core's start already ran the move once; this is an older AGOS's copy.)
    core.db.execute("DELETE FROM app_settings WHERE key = ?", (library.SPILL_MOVED,))
    assert library.move_spill_cap(core) == [a]
    assert config_file.get(config_file.read(home), KEY) is None
    core.engine._hermes(a, "config", "set", KEY, "1000000")  # his own choice later
    assert library.move_spill_cap(core) == []
    assert str(config_file.get(config_file.read(home), KEY)) == "1000000"
