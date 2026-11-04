"""Keys the owner pastes (ADR 0023): masked with Hermes's own masking before AGOS or
Hermes keeps his message (web chat and Telegram, one note for the agent).

Hermes's masking is stubbed by `_hermes_mask` (its key mask: 6 head, ..., 4 tail);
the real one runs where Hermes is installed (the last tests). No key-looking
literal is in this file: the fake key is built at run time.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from chat_rig import env, new_chat  # noqa: F401 - fixture

from agos_core.engine import owner_keys
from agos_core.hermes_plugin.agos_guard import keys

FAKE_KEY = "sk-or-v1-" + "a" * 44 + "b1c2"
SHOWN = "sk-or-...b1c2"


def _hermes_mask(text: str) -> str:
    """Hermes's redact_sensitive_text as far as these tests go (its _mask_token)."""
    return re.sub(r"(sk-or-)v1-[A-Za-z0-9]{20,}([A-Za-z0-9]{4})", r"\1...\2", text)


class _Helper:
    """keys.py's serve loop, in this process, with the stub above."""

    def __init__(self, broken: bool = False) -> None:
        self.broken = broken
        self.asked: list[str] = []

    def running(self) -> bool:
        return True

    def hide_many(self, texts: list[str]) -> list[tuple[str, list[dict[str, str]]]] | None:
        self.asked += texts
        if self.broken:
            return None
        return [keys.hide(t, _hermes_mask) for t in texts]


@pytest.fixture
def helper(monkeypatch: pytest.MonkeyPatch) -> _Helper:
    found = _Helper()
    monkeypatch.setitem(owner_keys._current, "helper", found)
    return found


def _inbox(core: Any) -> list[str]:
    return [
        str(r[0])
        for r in core.db.execute(
            "SELECT text FROM hermes_inbox WHERE kind != 'command' ORDER BY id"
        )
    ]


def _nowhere_in_agos(core: Any) -> None:
    """The key is in no table of agos.db."""
    for (table,) in core.db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND sql NOT LIKE 'CREATE VIRTUAL%'"
    ).fetchall():
        for row in core.db.execute(f'SELECT * FROM "{table}"').fetchall():
            assert FAKE_KEY not in json.dumps([str(v) for v in tuple(row)]), table


# ---- (A) his web messages ---------------------------------------------------------


def test_a_key_in_his_web_message_is_masked_before_anyone_keeps_it(
    env: Any,  # noqa: F811
    helper: _Helper,
) -> None:
    client, _fake, core, ws_id = env
    chat = new_chat(client, ws_id)
    r = client.post(
        f"/workspaces/{ws_id}/chats/{chat}/messages", json={"body": f"my key is {FAKE_KEY} ok"}
    )
    assert r.status_code == 201, r.text
    [text] = _inbox(core)
    assert text == f"my key is {SHOWN} ok\n\n{owner_keys.NOTE}"
    _nowhere_in_agos(core)
    # His edit of a message still in the queue is his words too.
    from agos_core.actions import chat as chat_actions

    queued = chat_actions.post_message(core, ws_id, chat, "first words")
    chat_actions.edit_message(core, ws_id, chat, queued, f"new key {FAKE_KEY}")
    assert _inbox(core)[-1] == f"new key {SHOWN}\n\n{owner_keys.NOTE}"
    _nowhere_in_agos(core)


def test_a_plain_message_goes_on_exactly_as_he_wrote_it(
    env: Any,  # noqa: F811
    helper: _Helper,
) -> None:
    client, _fake, core, ws_id = env
    chat = new_chat(client, ws_id)
    for body in ("Call me on +212612345678 tomorrow", "What is 2+2?"):
        assert (
            client.post(
                f"/workspaces/{ws_id}/chats/{chat}/messages", json={"body": body}
            ).status_code
            == 201
        )
    assert _inbox(core) == ["Call me on +212612345678 tomorrow", "What is 2+2?"]
    assert helper.asked  # each was asked


def test_when_hermes_cant_check_the_message_goes_on_unchanged_and_it_is_said_once(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, _fake, core, ws_id = env
    monkeypatch.setitem(owner_keys._current, "helper", _Helper(broken=True))
    monkeypatch.setattr(owner_keys, "_warned", type(owner_keys._warned)())
    chat = new_chat(client, ws_id)
    with caplog.at_level(logging.WARNING, logger="agos.owner_keys"):
        for _ in range(2):
            client.post(f"/workspaces/{ws_id}/chats/{chat}/messages", json={"body": "hi there"})
    assert _inbox(core) == ["hi there", "hi there"]
    said = [r for r in caplog.records if "not checked for keys" in r.getMessage()]
    assert len(said) == 1


def test_a_command_is_masked_without_the_note(helper: _Helper) -> None:
    assert owner_keys.hide(f"/queue use {FAKE_KEY}", command=True) == f"/queue use {SHOWN}"
    assert owner_keys.hide("/status", command=True) == "/status"


def test_hermes_marks_name_the_key_and_keep_phone_numbers() -> None:
    def mask(text: str) -> str:
        text = _hermes_mask(text)
        text = re.sub(r"\+212(\d{5})(\d{4})", r"+212****\2", text)
        return re.sub(r"(API_KEY=)\S+", r"\1***", text)

    secret = "hunter" + "2" * 10 + "xyZ9"
    masked, found = keys.hide(f"key {FAKE_KEY} tel +212612345678 API_KEY={secret} end", mask)
    assert masked == f"key {SHOWN} tel +212612345678 API_KEY=*** end"
    assert found == [
        {"kind": "sk-or-… key", "last4": "b1c2"},
        {"kind": "API_KEY value", "last4": "xyZ9"},
    ]
    assert keys.owner_text("nothing here", mask=mask) is None


# ---- (A) his Telegram messages (agos-guard, inside the gateway) -------------------------


def test_the_plugin_rewrites_his_telegram_message_with_the_key_masked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from agos_core.hermes_plugin.agos_guard import bridge as plugin

    agent = types.ModuleType("agent")
    redact = types.ModuleType("agent.redact")
    redact.redact_sensitive_text = lambda text, force=False, **_: _hermes_mask(text)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "agent", agent)
    monkeypatch.setitem(sys.modules, "agent.redact", redact)
    monkeypatch.setattr(plugin, "bridge", lambda: {"core": "x", "workspace": "w", "key": "k"})
    posted: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(plugin, "post", lambda path, body, timeout=0: posted.append((path, body)))

    def event(text: str) -> Any:
        source = types.SimpleNamespace(
            platform="telegram", chat_id="555", thread_id=None, user_id="555", chat_name=""
        )
        return types.SimpleNamespace(
            text=text, source=source, message_id="1", internal=False, metadata={}, media_urls=[]
        )

    got = asyncio.run(plugin.pre_gateway_dispatch(event(f"here {FAKE_KEY}"), object()))
    assert got == {"action": "rewrite", "text": f"here {SHOWN}\n\n{owner_keys.NOTE}"}
    assert posted == []  # a plain message: nothing before Hermes admits it, as before
    assert asyncio.run(plugin.pre_gateway_dispatch(event("hello"), object())) is None
    # His /command: AGOS's copy and Hermes's both get the masked words, no note.
    got = asyncio.run(plugin.pre_gateway_dispatch(event(f"/queue {FAKE_KEY}"), object()))
    assert got == {"action": "rewrite", "text": f"/queue {SHOWN}"}
    assert posted[-1][1]["text"] == f"/queue {SHOWN}"


def test_without_hermes_masking_the_plugin_lets_his_message_through_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from agos_core.hermes_plugin.agos_guard import bridge as plugin

    monkeypatch.setitem(sys.modules, "agent.redact", None)  # not importable
    monkeypatch.setattr(plugin, "bridge", lambda: {"core": "x", "workspace": "w", "key": "k"})
    source = types.SimpleNamespace(
        platform="telegram", chat_id="555", thread_id=None, user_id="555", chat_name=""
    )
    event = types.SimpleNamespace(
        text=f"x {FAKE_KEY}", source=source, message_id="2", internal=False, metadata={}
    )
    assert asyncio.run(plugin.pre_gateway_dispatch(event, object())) is None


# ---- real Hermes, where it is installed ---------------------------------------------------


def _real_hermes() -> str | None:
    hermes = shutil.which("hermes")
    if not hermes:
        return None
    from types import SimpleNamespace
    from typing import cast

    from agos_core.engine.models import hermes_python

    try:
        return hermes_python(cast(Any, SimpleNamespace(hermes_bin=hermes)))
    except Exception:  # noqa: BLE001 - no usable Hermes: skipped
        return None


def test_hermes_own_masking_in_its_helper_process() -> None:
    hermes = shutil.which("hermes")
    if hermes is None or _real_hermes() is None:
        pytest.skip("no Hermes install on this machine")
    helper = owner_keys.KeysHelper(hermes, str(Path.home()))
    try:
        answer = helper.hide_many([f"key {FAKE_KEY}", "call +212612345678", ""])
    finally:
        if helper._proc is not None:
            helper._proc.kill()
    assert answer is not None
    (masked, found), (phone, none), (empty, nothing) = answer
    assert FAKE_KEY not in masked and masked.endswith("b1c2") and found[0]["last4"] == "b1c2"
    assert phone == "call +212612345678" and none == [] and (empty, nothing) == ("", [])
