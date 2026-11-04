"""Hermes's Tool Search for the Co-Founder's tools (actions/tool_search.py): the
default is Hermes's own behaviour (nothing written); the switch reaches each root's
Co-Founder profile only, and going back unsets only what AGOS wrote."""

import json
from typing import Any

import pytest
from test_agent_profiles import add_agent
from test_library import env, ws  # noqa: F401 - fixture

from agos_core.actions import tool_search
from agos_core.db.app_settings import get_setting
from agos_core.engine import config_file


def test_tool_search_default_writes_nothing_and_the_switch_reaches_each_root(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    root = core.engine.profile_home(a)
    member = core.engine.profile_home(f"{a}--a-writer")

    def ts(home: Any) -> Any:
        return config_file.get(config_file.read(home), "tools.tool_search")

    # Hermes's own behaviour: nothing written anywhere.
    assert tool_search.keep_all(core) == 1 and ts(root) is None
    assert client.get("/preferences/tool-search").json() == {"eager": [], "defer": []}
    monkeypatch.setattr(tool_search, "_hermes_defer", lambda core: ["todo_list"])
    r = client.put("/preferences/tool-search", json={"eager": ["agos_action"], "defer": ["memory"]})
    assert r.status_code == 200, r.text
    found = ts(root)
    assert found["enabled"] is False or str(found["enabled"]).lower() == "off", found
    defer = found["defer"] if isinstance(found["defer"], list) else json.loads(found["defer"])
    assert defer == ["todo_list", "memory"]
    assert ts(member) is None  # members keep Hermes's own behaviour
    # Back to the default: what AGOS wrote goes, and nothing more is written.
    r = client.put("/preferences/tool-search", json={"eager": [], "defer": []})
    assert r.status_code == 200, r.text
    assert not ts(root)
    assert get_setting(core.db, tool_search.KEY, {})["written"] is False
