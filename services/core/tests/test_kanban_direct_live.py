"""A Kanban card read straight from Hermes's board database (engine/hermes_board.py)
is what the installed Hermes CLI prints: a board built with the real `hermes kanban`
commands (cards, comments, a block, parent/child links, a file, a finished card, an
archived one), then every field AGOS shows compared with `hermes kanban show --json`
and `hermes kanban attachments --json`. Skipped on a machine without Hermes.

Hermes runs in a scratch HOME and home of its own (with the install's runtime,
HERMES_RUNTIME_DIR) and the install's shared launcher must be left as it was. Its
first command in a new home prepares Hermes's dependencies for that home (about a
minute), so the board is built once for the module and removed afterwards."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from agos_core.engine import hermes_board
from agos_core.engine.hermes import child_env

HERMES = shutil.which("hermes")
TOOLS = Path.home() / ".hermes" / "tools"
LAUNCHER = Path.home() / ".hermes" / "hermes-agent" / ".hermes" / "bin" / "hermes"

pytestmark = pytest.mark.skipif(not HERMES, reason="no Hermes install on this machine")

Cli = Callable[..., str]


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Cli, Path, dict[str, str]]]:
    base = tmp_path_factory.mktemp("kanban-live")
    home, root = base / "home", base / "root"
    home.mkdir()
    root.mkdir()
    env = child_env(
        {
            "HOME": str(home),
            "HERMES_HOME": str(root),
            **({"HERMES_RUNTIME_DIR": str(TOOLS)} if TOOLS.is_dir() else {}),
        }
    )
    launcher = LAUNCHER.read_bytes() if LAUNCHER.is_file() else None

    def cli(*args: str) -> str:
        assert HERMES is not None
        done = subprocess.run(  # noqa: S603 - the installed Hermes, fixed argv
            [HERMES, "kanban", *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        assert done.returncode == 0, (args, done.stdout[-800:], done.stderr[-800:])
        return done.stdout

    def made(*args: str) -> str:
        return str(json.loads(cli("create", *args, "--json"))["id"])

    try:
        cards = {"research": made("Research", "--body", "find facts", "--assignee", "default")}
        cards["script"] = made(
            "Write the script",
            "--body",
            "The body\nwith two lines",
            "--assignee",
            "default",
            "--parent",
            cards["research"],
            "--goal",
        )
        cards["publish"] = made("Publish", "--parent", cards["script"], "--model", "gpt-x")
        cards["old"] = made("An old idea", "--created-by", "owner")
        cli("comment", cards["script"], "first", "--author", "owner")
        cli("comment", cards["script"], "second, from the user")
        cli("comment", cards["script"], "third, from a member", "--author", "default")
        notes = base / "notes.txt"
        notes.write_text("hello")
        cli("attach", cards["script"], str(notes), "--name", "notes.txt", "--author", "owner")
        cli("attach", cards["script"], str(notes), "--name", "again.txt")
        cli("complete", cards["research"], "--result", "facts found", "--summary", "The facts.")
        cli("block", cards["script"], "Which", "colour?", "--kind", "needs_input")
        cli("archive", cards["old"])
        yield cli, root, cards
    finally:
        if launcher is not None:
            assert LAUNCHER.read_bytes() == launcher, "a Hermes run rewrote the shared launcher"
        shutil.rmtree(base, ignore_errors=True)


def _shown_by_cli(cli: Cli, card: str) -> dict[str, Any]:
    """`hermes kanban show --json`, the fields AGOS reads (actions/kanban_board.py card)."""
    raw = json.loads(cli("show", card, "--json"))
    return {
        "task": {k: raw["task"][k] for k in hermes_board.TASK_FIELDS},
        "latest_summary": raw["latest_summary"],
        "parents": raw["parents"],
        "children": raw["children"],
        "comments": raw["comments"],
        "events": raw["events"],
    }


def test_a_card_read_from_the_board_is_what_hermess_cli_prints(
    built: tuple[Cli, Path, dict[str, str]],
) -> None:
    cli, root, cards = built
    db = hermes_board.board(root, root.parent / "home")
    assert db == root / "kanban.db"
    for name, card in cards.items():
        found = hermes_board.show(db, card)
        assert found is not None, name
        shown, _extra = found
        assert shown == _shown_by_cli(cli, card), name
        assert hermes_board.attachments(db, card) == json.loads(
            cli("attachments", card, "--json")
        ), name
    # What the board holds is really there (not two empty answers agreeing).
    script, _extra = hermes_board.show(db, cards["script"]) or ({}, {})
    assert script["task"]["status"] == "blocked" and script["parents"] == [cards["research"]]
    assert script["children"] == [cards["publish"]]
    assert [c["body"] for c in script["comments"]][:3] == [
        "first",
        "second, from the user",
        "third, from a member",
    ]
    assert any(e["kind"] == "blocked" for e in script["events"])
    assert _extra == {"goal_mode": 1, "block_kind": "needs_input"}
    research, _ = hermes_board.show(db, cards["research"]) or ({}, {})
    assert research["latest_summary"] == "The facts." and research["task"]["completed_at"]
    names = [a["filename"] for a in hermes_board.attachments(db, cards["script"]) or []]
    assert names == ["notes.txt", "again.txt"]
    publish, _ = hermes_board.show(db, cards["publish"]) or ({}, {})
    assert publish["task"]["model_override"] == "gpt-x"


def test_a_card_the_board_doesnt_have_is_none_like_the_clis_no_such_task(
    built: tuple[Cli, Path, dict[str, str]],
) -> None:
    cli, root, _cards = built
    db = hermes_board.board(root, root.parent / "home")
    assert hermes_board.show(db, "t_00000000") is None
    assert hermes_board.attachments(db, "t_00000000") is None
    with pytest.raises(AssertionError, match="no such task"):
        cli("show", "t_00000000", "--json")


class _Clean:
    """Hermes's masking stand-in (nothing secret in these lines)."""

    def mask_many(self, texts: list[str]) -> list[str]:
        return list(texts)


def test_mark_done_is_what_hermess_cli_takes(
    built: tuple[Cli, Path, dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mark done (actions/services/board/card_text.py complete_args) with the real Hermes: a card
    with no words is refused and Hermes says why on its stderr (what the owner reads,
    engine/hermes.py refusal_line); with his words it is done and holds them as its
    result and summary, read back the way the card's page reads it."""
    from agos_core.actions import kanban_board
    from agos_core.engine import hermes_redact
    from agos_core.engine.hermes import EngineError, SubprocessRunner

    cli, root, _cards = built
    card = str(json.loads(cli("create", "Tidy up", "--json"))["id"])
    db = hermes_board.board(root, root.parent / "home")
    shown, _extra = hermes_board.show(db, card) or ({}, {})
    assert kanban_board.done_needs_summary(shown["task"]["status"], shown["task"]["result"])
    monkeypatch.setitem(hermes_redact._current, "redactor", _Clean())
    env = {
        "HOME": str(root.parent / "home"),
        "HERMES_HOME": str(root),
        **({"HERMES_RUNTIME_DIR": str(TOOLS)} if TOOLS.is_dir() else {}),
    }
    assert HERMES is not None
    with pytest.raises(EngineError) as refused:
        SubprocessRunner().run(
            [HERMES, "kanban", *kanban_board.complete_args(card)], timeout=600, env=env
        )
    assert refused.value.reason == (
        f"cannot complete {card}: completion blocked: {card} has no result or summary"
        " evidence. Pass --result/--summary describing what was done (an empty completion"
        " is not evidence)."
    )
    words = "-Fixed the header\nand the footer"
    cli(*kanban_board.complete_args(card, words))
    shown, _extra = hermes_board.show(db, card) or ({}, {})
    assert (shown["task"]["status"], shown["task"]["result"]) == ("done", words)
    assert shown["latest_summary"] == words
    assert shown == _shown_by_cli(cli, card)
