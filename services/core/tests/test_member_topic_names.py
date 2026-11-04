"""In a topic Hermes routes to a member (gateway.profile_routes), every answer the
team's one bot sends there says who wrote it, like a group's room: the member's
display_name first, once (Hermes's transform_llm_output hook)."""

from pathlib import Path
from typing import Any

import pytest
from split_sources import split_source

from agos_core.hermes_plugin.agos_guard import bridge as plugin
from agos_core.hermes_plugin.agos_guard import bridge_stream


@pytest.fixture
def root(tmp_path: Path, monkeypatch: Any) -> Path:
    (tmp_path / "profiles" / "a-language-coach").mkdir(parents=True)
    (tmp_path / "profiles" / "a-language-coach" / "profile.yaml").write_text(
        "display_name: Language Coach\n"
    )
    (tmp_path / "config.yaml").write_text(
        "gateway:\n  profile_routes:\n"
        "    - name: agos-topic--100-5\n      platform: telegram\n"
        "      chat_id: '-100'\n      profile: a-language-coach\n      thread_id: '5'\n"
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    plugin._shared.pop("member_names", None)
    return tmp_path


def test_a_routed_topic_answer_says_who_wrote_it(root: Path) -> None:
    assert plugin._with_member_name("-100", "5", "Hello") == "**Language Coach:**\nHello"
    # Once: an answer that already says it is left as it is.
    once = plugin._with_member_name("-100", "5", "**Language Coach:**\nHello")
    assert once == "**Language Coach:**\nHello"


def test_other_places_are_left_alone(root: Path) -> None:
    assert plugin._with_member_name("-100", "3", "Hi") == "Hi"  # another topic
    assert plugin._with_member_name("-100", None, "Hi") == "Hi"  # the group itself
    assert plugin._with_member_name("7245299860", "", "Hi") == "Hi"  # his private chat
    assert plugin._with_member_name("-100", "5", "") == ""


def test_hermess_transform_hook_names_the_members_answer(root: Path, monkeypatch: Any) -> None:
    """Hermes's transform_llm_output in the member's routed turn (its session's chat
    and thread): the answer starts with the member's name; elsewhere it is untouched."""
    import sys
    import types

    env = {"HERMES_SESSION_CHAT_ID": "-100", "HERMES_SESSION_THREAD_ID": "5"}
    fake = types.ModuleType("gateway.session_context")
    fake.get_session_env = lambda name, default="": env.get(name, default)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gateway", types.ModuleType("gateway"))
    monkeypatch.setitem(sys.modules, "gateway.session_context", fake)
    assert plugin.transform_llm_output("Daba 00:43", platform="telegram") == (
        "**Language Coach:**\nDaba 00:43"
    )
    assert plugin.transform_llm_output("**Language Coach:**\nHi", platform="telegram") is None
    assert plugin.transform_llm_output("Hi", platform="agos") is None
    env["HERMES_SESSION_THREAD_ID"] = "3"
    assert plugin.transform_llm_output("Hi", platform="telegram") is None


def test_the_plugin_registers_the_hook() -> None:
    text = split_source(plugin)
    assert 'ctx.register_hook("transform_llm_output", bridge_stream.transform_llm_output)' in text


def test_during_a_members_turn_the_names_come_from_the_root(root: Path, monkeypatch: Any) -> None:
    """Hermes points HERMES_HOME at the member's profile during its routed turn: the
    names are read from the root the plugin is installed in."""
    installed = root / "plugins" / "agos-guard" / "bridge.py"
    installed.parent.mkdir(parents=True)
    installed.write_text("")
    monkeypatch.setattr(bridge_stream, "__file__", str(installed))  # _plugin_root reads it
    monkeypatch.setenv("HERMES_HOME", str(root / "profiles" / "a-language-coach"))
    plugin._shared.pop("member_names", None)
    assert plugin._with_member_name("-100", "5", "Hi") == "**Language Coach:**\nHi"


def test_names_are_read_with_hermess_own_yaml(monkeypatch: Any) -> None:
    """Hermes's runtime has no PyYAML (it ships hermes_yaml): the plugin reads with
    Hermes's utils.load_yaml_file_readonly first."""
    import sys
    import types

    fake = types.ModuleType("utils")
    fake.load_yaml_file_readonly = lambda path: {"read by": "hermes"}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "utils", fake)
    assert plugin._yaml_loader()("x") == {"read by": "hermes"}
    source = split_source(plugin)  # the facade and its parts (bridge_stream.py)
    assert "yaml.safe_load(config" not in source
