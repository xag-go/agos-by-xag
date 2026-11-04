"""The Office's live refresh asks one cheap core read every 2 s: its fingerprint,
kept while none of the stores it is read from moved (AGOS's rows, Hermes's board,
the root's Hermes homes), so an unchanged Office costs no team / board / looks read
(they were ~0.25 s + ~0.3 s per tick)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from test_hermes_roots import _new, roots_env  # noqa: F401 - fixture

from agos_core.actions import agent_profiles
from agos_core.actions.workers import team as real_team
from agos_core.api import office as office_api


def _counting(monkeypatch: Any) -> list[str]:
    computed: list[str] = []

    def team(core: Any, workspace_id: str) -> Any:
        computed.append(workspace_id)
        return real_team(core, workspace_id)

    monkeypatch.setattr(office_api, "team", team)
    return computed


def _stamp(client: Any, ws: str) -> str:
    got = client.get(f"/workspaces/{ws}/office/stamp")
    assert got.status_code == 200, got.text
    stamp: str = got.json()["stamp"]
    return stamp


def test_an_unchanged_office_answers_without_reading_again(
    roots_env: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    client, _runner, _tmp, _core = roots_env
    ws = _new(client)
    computed = _counting(monkeypatch)
    first = _stamp(client, ws)
    _stamp(client, ws)  # what the first read itself touched has settled
    settled = len(computed)
    assert [_stamp(client, ws) for _ in range(3)] == [first] * 3
    assert len(computed) == settled


def test_a_change_in_agos_or_hermes_is_read_again(roots_env: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, _runner, _tmp, core = roots_env
    ws = _new(client)
    computed = _counting(monkeypatch)
    before = _stamp(client, ws)
    _stamp(client, ws)
    # AGOS's rows: his look for the Co-Founder (what the Office shows changes).
    put = client.put(
        f"/workspaces/{ws}/office/cofounder",
        json={"pet": "dog", "pet_name": "Rex", "colour": "teal", "item": "lamp"},
    )
    assert put.status_code == 204, put.text
    moved = _stamp(client, ws)
    assert moved != before
    # Hermes's stores: its board and the root's config are read again when they move.
    seen = len(computed)
    board: Path = agent_profiles.board_db(core, ws)
    board.parent.mkdir(parents=True, exist_ok=True)
    board.write_bytes(b"")
    _stamp(client, ws)
    assert len(computed) == seen + 1
    config = core.engine.profile_home(ws) / "config.yaml"
    config.write_text(config.read_text() + "\n# touched\n" if config.is_file() else "x: 1\n")
    _stamp(client, ws)
    assert len(computed) == seen + 2


def test_the_page_and_its_live_refresh_agree_on_one_read(
    roots_env: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    """The page reads everything in one ask (the team once) and gets the fingerprint
    its refresh then finds unchanged, without reading again."""
    client, _runner, _tmp, _core = roots_env
    ws = _new(client)
    computed = _counting(monkeypatch)
    _stamp(client, ws)  # settle what a first read touches
    view = client.get(f"/workspaces/{ws}/office/view")
    assert view.status_code == 200, view.text
    shown = view.json()
    assert set(shown) == {"team", "board", "looks", "stamp"}
    assert "cofounder" in shown["looks"] and shown["team"]["cofounder"]["title"] == "Co-Founder"
    read = len(computed)
    assert _stamp(client, ws) == shown["stamp"]
    assert len(computed) == read
