"""Agents always know the real time: Hermes's pre_llm_call context on every turn
its gateway didn't stamp, never twice; the sandbox and MCP servers in his zone."""

from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from split_sources import split_source

from agos_core.engine import mcp_runner
from agos_core.engine.rules import profile_config, sandbox_env
from agos_core.hermes_plugin.agos_guard import bridge, clock

REPO = Path(__file__).resolve().parents[3]
STAMP = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


@pytest.fixture(autouse=True)
def hermes_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hermes's own formatter and timezone (as in its tree, v0.22.2)."""
    stamps = types.ModuleType("gateway.message_timestamps")

    def fmt(ts: Any, tz: Any = None) -> str:
        return "[Fri 2026-10-16 18:40:53 BST]"

    stamps.format_message_timestamp = fmt  # type: ignore[attr-defined]
    hermes_time = types.ModuleType("hermes_time")
    hermes_time.get_timezone = lambda: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gateway", types.ModuleType("gateway"))
    monkeypatch.setitem(sys.modules, "gateway.message_timestamps", stamps)
    monkeypatch.setitem(sys.modules, "hermes_time", hermes_time)
    monkeypatch.setattr(bridge, "bridge", lambda: None)


def turn(text: Any, platform: str = "") -> Any:
    history = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "ok"}]
    history.append({"role": "user", "content": text})
    return bridge.pre_llm_call("s1", "t1", platform=platform, conversation_history=history)


@pytest.mark.parametrize("platform", ["tui", "cron", "subagent", "cli", ""])
def test_a_turn_without_the_gateway_stamp_gets_the_time(platform: str) -> None:
    """Rooms (TUI prompt.submit), cron runs, subagents, Kanban workers (hermes chat -q)."""
    got = turn("[Discussion: plan]\nUser (user): hello", platform)
    assert got == {"context": "[Current time: Fri 2026-10-16 18:40:53 BST]"}


def test_a_gateway_turn_is_never_stamped_twice() -> None:
    assert turn("[Fri 2026-10-16 18:40:00 BST] hello", "agos") is None
    assert turn("[Fri 2026-10-16 18:40:00 +01] hi", "telegram") is None
    # Hermes may put its own note before the stamp.
    note = "[System note: A new message has arrived.]\n\n[Fri 2026-10-16 18:40:00 BST] hi"
    assert turn(note, "agos") is None
    # A native-image turn (list content) keeps its stamp in a text part.
    parts = [{"type": "text", "text": "[Fri 2026-10-16 18:40:00 BST] look"}, {"type": "image"}]
    assert turn(parts, "telegram") is None
    # The gateway with message_timestamps off: no stamp, so the time is added once.
    assert turn("hello", "agos") is not None


def test_the_time_is_added_even_when_agos_is_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_: Any, **__: Any) -> None:
        raise RuntimeError("AGOS down")

    monkeypatch.setattr(bridge, "_turn_opens", broken)
    assert turn("hi", "agos") is not None


@pytest.mark.parametrize("platform", ["telegram", "agos"])
def test_a_persons_message_carries_the_language_to_answer_in(platform: str) -> None:
    """His rule sits in the system prompt, far from a long turn's end: it is said
    again next to his words on every turn of his (Telegram and AGOS chats)."""
    history = [{"role": "user", "content": "[Fri 2026-10-16 18:40:00 BST] db chno ba9i?"}]
    got = bridge.pre_llm_call(
        "s1", "t1", platform=platform, sender_id="7245299860", conversation_history=history
    )
    assert got == {"context": bridge.LANGUAGE_NOTE}  # stamped by the gateway: no time
    note = bridge.LANGUAGE_NOTE
    assert "Darija in Latin letters" in note and "English" in note
    unstamped = bridge.pre_llm_call(
        "s1", "t2", platform=platform, sender_id="7245299860", conversation_history=[]
    )
    assert unstamped is not None
    assert unstamped["context"].endswith(bridge.LANGUAGE_NOTE)
    assert unstamped["context"].startswith("[Current time:")


@pytest.mark.parametrize("platform", ["cron", "cli", "tui", ""])
def test_no_language_note_where_no_person_wrote(platform: str) -> None:
    got = bridge.pre_llm_call("s1", "t1", platform=platform, conversation_history=[])
    assert got is not None and bridge.LANGUAGE_NOTE not in got["context"]


def test_one_time_in_what_the_model_gets() -> None:
    """What Hermes sends: the gateway's stamp or the hook's, exactly one."""
    for message in ("[Discussion]\n@writer: draft", "[Fri 2026-10-16 18:40:00 BST] hello"):
        got = turn(message)
        sent = message + ("\n\n" + got["context"] if got else "")
        assert len(STAMP.findall(sent)) == 1, sent


def test_the_hook_is_registered_and_cache_safe() -> None:
    """pre_llm_call context goes into this turn's user message only (Hermes's
    api_content sidecar), never into the system prompt: the plugin returns it, and
    adds nothing else to the turn than the time and the language note (fixed text)."""
    source = split_source(bridge)
    assert 'ctx.register_hook("pre_llm_call", bridge_hooks.pre_llm_call)' in source
    assert "timed = clock.context(conversation_history)" in source
    assert "notes.append(LANGUAGE_NOTE)" in source
    assert "system_prompt" not in Path(clock.__file__).read_text().split('"""', 2)[2]


def test_the_sandbox_knows_the_owners_zone() -> None:
    config = profile_config(image="img:1", mounts=[], zone="Africa/Casablanca")
    assert json.loads(config["terminal.docker_env"]) == {"TZ": "Africa/Casablanca"}
    # Behind the egress proxy: its env stays, with TZ.
    net = {"terminal.docker_env": json.dumps({"HTTP_PROXY": "http://p:1"})}
    config = profile_config(image="img:1", mounts=[], network=net, zone="Europe/Paris")
    assert json.loads(config["terminal.docker_env"]) == {
        "HTTP_PROXY": "http://p:1",
        "TZ": "Europe/Paris",
    }
    # No zone: no TZ (the server's own time, as Hermes's `timezone` unset).
    assert json.loads(profile_config(image="i", mounts=[])["terminal.docker_env"]) == {}
    assert json.loads(sandbox_env('{"TZ": "Old/Zone", "A": "1"}', "")) == {"A": "1"}


def test_mcp_servers_know_the_owners_zone(tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []
    seen_env: list[str] = []

    def docker(*args: str, **_: Any) -> str:
        calls.append(args)
        if args[0] == "run" and "--env-file" in args:
            seen_env.append(Path(args[args.index("--env-file") + 1]).read_text())
        if args[0] == "port":
            return "0.0.0.0:49000\n"
        return ""

    mcp_runner.ensure(
        docker,
        profile="agos-w1",
        name="notes",
        command="npx -y notes-mcp",
        files_dir=tmp_path,
        image="agos-sandbox:1",
        zone="Africa/Casablanca",
        token="relay-token",
    )
    assert any("TZ=Africa/Casablanca" in env for env in seen_env)
    spec = next(a for a in calls if a[0] == "run" and "--env-file" in a)
    assert any("Africa/Casablanca" in part for part in spec if part.startswith("agos-mcp-spec="))


def test_the_sandbox_image_has_tzdata() -> None:
    """Without tzdata a TZ name is not known to `date` in the container."""
    dockerfile = (REPO / "docker" / "sandbox" / "Dockerfile").read_text()
    assert re.search(r"^\s+tzdata[; \\]", dockerfile, re.M)
