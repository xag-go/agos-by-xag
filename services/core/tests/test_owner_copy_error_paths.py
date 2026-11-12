"""The reworded owner-facing error paths run on fakes (no real engine).

Spec docs/specs/2026-11-04-no-engine-name.md: the owner-copy rework changed the
words of these error branches ("The engine isn't available.", "The engine didn't
take it: …"). test_owner_copy_no_hermes.py proves the words carry no engine name;
these tests EXECUTE the branches with an absent or failing fake engine, so the
changed lines are covered without a real Hermes install (the real-engine files
covering them are hermes-marked and skip on CI)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agos_core.actions import held_writes, hermes_settings, key_pools, tool_keys
from agos_core.actions.errors import ActionError
from agos_core.db import workspaces
from agos_core.db.connection import open_database
from agos_core.engine.hermes import EngineError

WS = "ws-a"


@pytest.fixture
def core() -> Any:
    db = open_database(":memory:")
    workspaces.insert_workspace(db, workspace_id=WS, name=WS, description="")
    return SimpleNamespace(db=db, engine=None)


def _raises(call: Any, said: str) -> ActionError:
    with pytest.raises(ActionError) as caught:
        call()
    assert said in str(caught.value), caught.value
    return caught.value


# --- tool keys -----------------------------------------------------------------


def test_tool_keys_without_an_engine_say_it_is_unavailable(core: Any) -> None:
    _raises(lambda: tool_keys.read(core, WS), "The engine isn't available.")


def test_tool_keys_before_the_root_is_made_say_try_again(core: Any, tmp_path: Path) -> None:
    core.engine = SimpleNamespace(split=lambda ws: ("", ""), profile_home=lambda ws: tmp_path)
    _raises(lambda: tool_keys.read(core, WS), "This workspace isn't set up yet.")


def test_a_reserved_name_is_kept_for_the_engine_and_agos() -> None:
    said = tool_keys._managed_elsewhere("HERMES_ANYTHING")
    assert said == "This name is kept for the engine and AGOS themselves."


# --- key pools -------------------------------------------------------------------


def test_key_pool_reads_without_an_engine_say_it_is_unavailable(core: Any, tmp_path: Path) -> None:
    _raises(lambda: key_pools._listed(core, tmp_path, kept=False), "The engine isn't available.")
    _raises(lambda: key_pools._pool(core, {"do": "move"}), "The engine isn't available.")
    _raises(lambda: key_pools._keys(core, {"do": "set"}), "The engine isn't available.")
    _raises(lambda: key_pools._everywhere(core, {"do": "remove"}), "The engine isn't available.")


def test_a_key_pool_the_engine_cannot_read_says_so(core: Any, tmp_path: Path) -> None:
    def broken(home: Path, job: dict[str, Any]) -> dict[str, Any]:
        raise EngineError("pool gone")

    core.engine = SimpleNamespace(
        settings=SimpleNamespace(hermes_home=tmp_path), credential_pool=broken
    )
    _raises(lambda: key_pools._pool(core, {"do": "move"}), "The engine's key pool couldn't be read")


def test_a_managed_key_write_the_engine_refuses_says_so(core: Any) -> None:
    def broken(job: dict[str, Any]) -> dict[str, Any]:
        raise EngineError("no")

    core.engine = SimpleNamespace(managed_keys=broken)
    _raises(lambda: key_pools._keys(core, {"do": "set"}), "The engine didn't take it")


def test_a_bad_provider_name_is_refused() -> None:
    _raises(lambda: key_pools._check("not a provider!"), "Pick one of the engine's providers.")


def test_a_key_missing_from_the_pool_is_a_404() -> None:
    error = _raises(
        lambda: key_pools._entry({"providers": []}, "anthropic", "k1"),
        "No such key in the engine's pool.",
    )
    assert error.status == 404


# --- held writes -------------------------------------------------------------------


@pytest.fixture
def one_agent(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(held_writes, "_profiles", lambda core, ws: [("agos-ws-a", "Co-Founder")])
    return "agos-ws-a"


def test_held_writes_without_an_engine_say_it_is_unavailable(core: Any, one_agent: str) -> None:
    _raises(lambda: held_writes.read(core, WS), "The engine isn't available.")
    _raises(
        lambda: held_writes.decide(core, WS, one_agent, "memory", "abcd1234", True),
        "The engine isn't available.",
    )
    _raises(
        lambda: held_writes.decide_group(core, WS, one_agent, "memory", ["abcd1234"], True),
        "The engine isn't available.",
    )
    _raises(
        lambda: held_writes.undo(core, WS, one_agent, "memory", {"kept": "x"}),
        "The engine isn't available.",
    )


def test_a_decision_the_engine_refuses_says_so(core: Any, one_agent: str, tmp_path: Path) -> None:
    def broken(home: Path, subsystem: str, pending_id: str, approve: bool, *, keep: bool) -> Any:
        raise EngineError("no")

    core.engine = SimpleNamespace(decide_pending=broken, profile_home=lambda key: tmp_path)
    _raises(
        lambda: held_writes.decide(core, WS, one_agent, "memory", "abcd1234", True),
        "The engine didn't take it",
    )


def test_a_decision_the_engine_does_not_apply_says_so(
    core: Any, one_agent: str, tmp_path: Path
) -> None:
    core.engine = SimpleNamespace(
        decide_pending=lambda *a, **k: {"found": True, "gone": False, "text": ""},
        profile_home=lambda key: tmp_path,
    )
    _raises(
        lambda: held_writes.decide(core, WS, one_agent, "memory", "abcd1234", True),
        "The engine didn't apply it",
    )


def test_an_explanation_needs_the_engine(
    core: Any, one_agent: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = {
        "profile": one_agent,
        "subsystem": "memory",
        "id": "abcd1234",
        "agent": "Co-Founder",
        "target": "MEMORY.md",
        "ops": [],
        "detail": "x",
    }
    monkeypatch.setattr(held_writes, "read", lambda core, ws: {"items": [item]})
    _raises(
        lambda: held_writes.explain(core, WS, one_agent, "memory", "abcd1234"),
        "The engine isn't available.",
    )

    from agos_core.hermes_gateway import cli as hermes_cli

    def broken(engine: Any, ws: str, *args: Any, **kwargs: Any) -> str:
        raise EngineError("no")

    core.engine = SimpleNamespace()
    monkeypatch.setattr(hermes_cli, "walled_cli", broken)
    _raises(
        lambda: held_writes.explain(core, WS, one_agent, "memory", "abcd1234"),
        "The engine didn't explain it",
    )


def test_an_undo_with_nothing_kept_or_a_refusing_engine_says_so(
    core: Any, one_agent: str, tmp_path: Path
) -> None:
    _raises(
        lambda: held_writes.undo(core, WS, one_agent, "memory", None),
        "The engine gave nothing to put it back with.",
    )

    def broken(home: Path, subsystem: str, kept: dict[str, Any]) -> Any:
        raise EngineError("no")

    core.engine = SimpleNamespace(undo_pending=broken, profile_home=lambda key: tmp_path)
    _raises(
        lambda: held_writes.undo(core, WS, one_agent, "memory", {"kept": "x"}),
        "The engine didn't take it",
    )
    core.engine = SimpleNamespace(
        undo_pending=lambda *a: {"ok": False, "error": "it moved"},
        profile_home=lambda key: tmp_path,
    )
    _raises(lambda: held_writes.undo(core, WS, one_agent, "memory", {"kept": "x"}), "it moved")


# --- the engine settings the Co-Founder changes from chat ---------------------------


def test_engine_settings_without_an_engine_say_the_workspace_is_unavailable(core: Any) -> None:
    _raises(
        lambda: hermes_settings.write(core, WS, {"goals.max_turns": "5"}),
        "This workspace isn't available.",
    )


def test_an_engine_setting_the_engine_refuses_says_so(
    core: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agos_core.hermes_gateway import cli as hermes_cli

    def broken(engine: Any, ws: str, *args: str) -> str:
        raise EngineError("no")

    monkeypatch.setattr(hermes_settings, "_own", lambda core, ws: {})
    monkeypatch.setattr(hermes_settings, "defaults", lambda core: {})
    monkeypatch.setattr(hermes_cli, "cli", broken)
    core.engine = SimpleNamespace()
    _raises(
        lambda: hermes_settings.write(core, WS, {"goals.max_turns": "5"}),
        "The engine didn't take it",
    )


# --- the other engine cards without an engine ---------------------------------------


def test_the_other_engine_cards_without_an_engine_say_it_is_unavailable(core: Any) -> None:
    from agos_core.actions import hermes_fallback, hermes_helper_models, hermes_voice

    _raises(lambda: hermes_helper_models._schema(core), "The engine isn't available.")
    _raises(lambda: hermes_voice._fields(core), "The engine isn't available.")
    _raises(lambda: hermes_fallback.write(core, []), "The engine isn't available.")


def test_a_time_limit_agos_does_not_show_is_refused(core: Any) -> None:
    from agos_core.actions import hermes_time_limits

    _raises(
        lambda: hermes_time_limits.check({"bogus": 5}),
        "bogus isn't one of the engine's time limits here.",
    )
    _raises(lambda: hermes_time_limits.write(core, {}), "The engine isn't available.")
