"""The agos-guard plugin's part of the Telegram bot: the team's members in Hermes's "/"
menu (Hermes's public plugin API only) and AGOS's card buttons it takes the presses of
(moved out of test_hermes_channel.py and test_channels.py)."""

from typing import Any

from split_parts import whole_text
from split_sources import split_source


def test_the_plugin_puts_the_members_in_hermess_menu(tmp_path: Any, monkeypatch: Any) -> None:
    """The agos-guard plugin follows the policy file: each member is its command
    (Hermes's menu lists plugin commands); a member gone is taken out."""
    import json as _json
    import sys
    import types

    from agos_core.hermes_plugin.agos_guard import bridge as plugin

    monkeypatch.setitem(
        sys.modules, "hermes_constants", types.SimpleNamespace(get_hermes_home=lambda: tmp_path)
    )

    commands: dict[str, Any] = {}

    class Registration:
        """Hermes's PluginRegistration: dispose() releases exactly this command."""

        def __init__(self, name: str) -> None:
            self.name = name

        def dispose(self) -> None:
            commands.pop(self.name, None)

    class Ctx:
        """Only Hermes's public plugin API: no _manager to reach into."""

        def register_command(self, name: str, handler: Any, description: str = "") -> Any:
            commands[name] = {"handler": handler, "description": description}
            return Registration(name)

    ctx = Ctx()
    monkeypatch.setitem(plugin._ctx, "ctx", ctx)
    monkeypatch.setattr(plugin, "_members", {})
    monkeypatch.setattr(plugin, "_member_handles", {})
    policy = tmp_path / "agos-guard.json"
    policy.write_text(
        _json.dumps({"members": [{"command": "script_writer", "title": "Script Writer"}]})
    )
    assert plugin._sync_members() is True
    assert commands["script_writer"]["description"] == "Script Writer"
    assert "@script-writer" in commands["script_writer"]["handler"]("x")
    assert plugin._sync_members() is False  # nothing changed
    policy.write_text(_json.dumps({"members": [{"command": "script_writer", "title": "Scripts"}]}))
    assert plugin._sync_members() is True  # a new title: released, then registered again
    assert commands["script_writer"]["description"] == "Scripts"
    policy.write_text(_json.dumps({"members": []}))
    assert plugin._sync_members() is True and commands == {}
    source = split_source(plugin)  # the facade and its parts (bridge_menu.py)
    assert "_plugin_commands" not in source and "_manager" not in source


def test_every_button_agos_sends_reaches_agos_through_hermes() -> None:
    """The workspace's Hermes bot takes the presses: each button AGOS puts on a card
    must match the plugin's pattern, or pressing it does nothing."""
    import re as regex

    from agos_core.hermes_plugin.agos_guard.bridge import AGOS_BUTTONS

    source = whole_text("actions/channels.py")  # the facade and its parts (buttons.py)
    made = set(regex.findall(r'fullmatch\(r"([a-z]+):', source))
    samples = {
        "chatcmd": "chatcmd:deny:1",
        "tok": "tok:go:t_1a2b",
        "kask": "kask:once:1",
        "krev": "krev:ok:t_1a2b",
        "fdone": "fdone:t_1a2b",  # Done on one of the Founder's tasks (actions/founder.py)
    }
    assert made <= set(samples), made - set(samples)
    for data in samples.values():
        assert regex.match(AGOS_BUTTONS, data), data
    # Gone: the Co-Founder's actions, requests and proposals are said in its Hermes
    # conversation; Hermes's own approvals use Hermes's own buttons (ea:…).
    for gone in ("act:approve:1", "aprop:7", "prop:1", "cap:no:1", "ea:once:1", "plan:yes:1"):
        assert not regex.match(AGOS_BUTTONS, gone), gone
