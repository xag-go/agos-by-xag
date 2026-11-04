"""The plugin keeps no copy of Hermes's session index: after a restart it asks
Hermes's own SessionStore (or its sessions.json mirror) which session a Telegram
chat continues, and the old agos-bridge-sessions.json goes once."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from agos_core.hermes_plugin.agos_guard import bridge as plugin


def _entry(key: str, chat: str, thread: str | None) -> Any:
    origin = SimpleNamespace(platform="telegram", chat_id=chat, thread_id=thread)
    return SimpleNamespace(session_key=key, origin=origin, updated_at=datetime.now(UTC))


def test_a_chat_continues_hermes_s_newest_session(monkeypatch: Any, tmp_path: Path) -> None:
    store = SimpleNamespace(
        list_sessions=lambda: [  # newest first, as Hermes lists them
            _entry("agent:a-writer:telegram:group:-100:7", "-100", "7"),
            _entry("agent:main:telegram:group:-100:7", "-100", "7"),
            _entry("agent:main:telegram:dm:42", "42", None),
        ]
    )
    monkeypatch.setattr(plugin, "_runner", lambda: SimpleNamespace(session_store=store))
    monkeypatch.setattr(plugin, "_home", lambda: tmp_path)
    monkeypatch.setitem(plugin._ctx, "adapter", None)
    plugin._keys.clear()
    assert plugin._key_for("-100:7") == "agent:a-writer:telegram:group:-100:7"
    assert plugin._key_for("42:0") == "agent:main:telegram:dm:42"
    assert plugin._key_for("9:0") == "agent:main:telegram:dm:9"  # Hermes's default
    plugin._remember_key("9:0", "agent:main:telegram:dm:9:x")
    assert plugin._key_for("9:0") == "agent:main:telegram:dm:9:x"  # memory only
    assert not (tmp_path / plugin.OLD_KEYS_FILE).exists()
    plugin._keys.clear()


def test_without_a_store_hermes_s_sessions_json_answers(monkeypatch: Any, tmp_path: Path) -> None:
    (tmp_path / "sessions").mkdir()
    (tmp_path / "sessions" / "sessions.json").write_text(
        '{"agent:main:telegram:group:-5:3": {"updated_at": "2026-01-01"}}'
    )
    monkeypatch.setattr(plugin, "_runner", lambda: None)
    monkeypatch.setattr(plugin, "_home", lambda: tmp_path)
    monkeypatch.setitem(plugin._ctx, "adapter", None)
    plugin._keys.clear()
    assert plugin._key_for("-5:3") == "agent:main:telegram:group:-5:3"


def test_the_old_copy_goes_once(monkeypatch: Any, tmp_path: Path) -> None:
    old = tmp_path / plugin.OLD_KEYS_FILE
    old.write_text('{"1:0": "agent:main:telegram:dm:1"}')
    monkeypatch.setattr(plugin, "_home", lambda: tmp_path)
    plugin.drop_old_keys_file()
    plugin.drop_old_keys_file()  # safe to repeat
    assert not old.exists()
