"""Mark done on a board card, the way Hermes's own dashboard does it.

Hermes refuses `hermes kanban complete` on a card that has no words on what was
done (its empty-completion gate, hermes_cli/kanban_db.py _gate_empty_completion:
any status but review, no stored result). Its dashboard asks for a completion
summary first and sends it as the card's result and summary. AGOS's card says
when that is needed (doneNeedsSummary), sends his words with Hermes's own flags,
never makes some up, and when Hermes refuses any board write the owner reads
Hermes's own reason, not only "hermes failed".
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from test_engine_sync import MODEL, env  # noqa: F401 - fixture

from agos_core.actions import kanban_board
from agos_core.engine import hermes_redact
from agos_core.engine.hermes import EngineError, SubprocessRunner, refusal_line

EMPTY = (
    "cannot complete {0}: completion blocked: {0} has no result or summary evidence. Pass"
    " --result/--summary describing what was done (an empty completion is not evidence)."
)


def _asked(runner: Any) -> list[list[str]]:
    """The Kanban commands AGOS ran with Hermes's CLI (its exact argv after `hermes`)."""
    return [c[1:] for c in runner.calls if Path(c[0]).name == "hermes" and c[1:2] == ["kanban"]]


def _ready_card(client: Any) -> tuple[str, str]:
    ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
    made = client.post(f"/workspaces/{ws}/kanban", json={"title": "Tidy up", "member": "cofounder"})
    assert made.status_code == 201, made.text
    return ws, made.json()["id"]


def test_mark_done_asks_for_words_and_sends_them_as_hermess_summary(env: Any) -> None:  # noqa: F811
    client, runner, _tmp = env
    ws, card = _ready_card(client)
    board = runner.kanban[f"agos-{ws}"]
    assert board[card]["status"] == "ready"
    shown = client.get(f"/workspaces/{ws}/kanban/{card}").json()
    assert "done" in shown["actions"] and shown["doneNeedsSummary"] is True

    # No words (or only blanks): AGOS sends no flag, Hermes refuses, the owner reads why.
    for body in ({"action": "done"}, {"action": "done", "summary": "  \n "}):
        runner.calls.clear()
        r = client.post(f"/workspaces/{ws}/kanban/{card}/act", json=body)
        assert r.status_code == 400, r.text
        assert r.json()["detail"] == f"The board refused: {EMPTY.format(card)}"
        assert _asked(runner) == [["kanban", "complete", card]]
        assert board[card]["status"] == "ready"

    # His words: Hermes's own result and summary flags, his text as he wrote it.
    runner.calls.clear()
    words = "Fixed the header\n-and the footer"
    r = client.post(
        f"/workspaces/{ws}/kanban/{card}/act", json={"action": "done", "summary": f"  {words} "}
    )
    assert r.status_code == 204, r.text
    assert _asked(runner) == [
        ["kanban", "complete", card, f"--result={words}", f"--summary={words}"]
    ]
    assert (board[card]["status"], board[card]["result"]) == ("done", words)
    shown = client.get(f"/workspaces/{ws}/kanban/{card}").json()
    assert shown["summary"] == words  # the card's "Latest result"
    assert "done" not in shown["actions"] and shown["doneNeedsSummary"] is False


def test_a_card_hermes_completes_without_words_asks_for_none(env: Any) -> None:  # noqa: F811
    """Review (the owner approving is the record) and a card that holds a result
    complete as before: no box, no flag."""
    client, runner, _tmp = env
    ws, card = _ready_card(client)
    board = runner.kanban[f"agos-{ws}"]
    board[card]["status"] = "review"
    shown = client.get(f"/workspaces/{ws}/kanban/{card}").json()
    assert "done" in shown["actions"] and shown["doneNeedsSummary"] is False
    runner.calls.clear()
    r = client.post(f"/workspaces/{ws}/kanban/{card}/act", json={"action": "done"})
    assert r.status_code == 204, r.text
    assert _asked(runner) == [["kanban", "complete", card]]
    assert board[card]["status"] == "done"

    other = client.post(f"/workspaces/{ws}/kanban", json={"title": "Half", "member": "cofounder"})
    held = other.json()["id"]
    board[held].update(status="blocked", result="Half of it, by the worker")
    shown = client.get(f"/workspaces/{ws}/kanban/{held}").json()
    assert "done" in shown["actions"] and shown["doneNeedsSummary"] is False


def test_the_rule_is_hermess_empty_completion_gate() -> None:
    need = kanban_board.done_needs_summary
    assert need("review", None) is False
    assert need("review", "") is False
    for status in ("ready", "running", "blocked", "todo"):
        assert need(status, None) is True
        assert need(status, " \n") is True
        assert need(status, "done by hand") is False
    assert kanban_board.complete_args("t_1") == ["complete", "t_1"]
    assert kanban_board.complete_args("t_1", "   ") == ["complete", "t_1"]
    assert kanban_board.complete_args("t_1", " -x ") == [
        "complete",
        "t_1",
        "--result=-x",
        "--summary=-x",
    ]


def test_any_refused_board_write_says_hermess_reason(env: Any) -> None:  # noqa: F811
    client, runner, _tmp = env
    ws, card = _ready_card(client)
    real = runner.run

    def refusing(args: Any, *, timeout: float, env: dict[str, str] | None = None) -> str:
        if list(args[1:3]) == ["kanban", "block"]:
            raise EngineError(
                "hermes failed", reason=f"cannot block {card} (unknown id or terminal state)"
            )
        if list(args[1:3]) == ["kanban", "archive"]:
            raise EngineError("hermes did not answer")  # no reason: as before
        return str(real(args, timeout=timeout, env=env))

    runner.run = refusing
    r = client.post(f"/workspaces/{ws}/kanban/{card}/act", json={"action": "block"})
    assert r.status_code == 400
    assert r.json()["detail"] == (
        f"The board refused: cannot block {card} (unknown id or terminal state)"
    )
    r = client.post(f"/workspaces/{ws}/kanban/{card}/act", json={"action": "archive"})
    assert r.json()["detail"] == "The board didn't answer: hermes did not answer"


class _Masking:
    """Hermes's masking stand-in: says every text is clean (the real one is Hermes's
    agent/redact.py, tests/test_command_output_masked_by_hermes.py)."""

    def mask_many(self, texts: list[str]) -> list[str]:
        return [t.replace("sk-secret", "sk-***") for t in texts]


def _fails(script: str) -> EngineError:
    with pytest.raises(EngineError) as caught:
        SubprocessRunner().run([sys.executable, "-c", script], timeout=30)
    return caught.value


def test_a_failed_hermes_command_carries_hermess_own_line(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(hermes_redact._current, "redactor", _Masking())
    error = _fails(
        "import sys; print('Completed t_0'); "
        "print('warning: slow disk', file=sys.stderr); "
        "print('cannot attach /home/agos/.hermes/roots/agos-a/kanban/notes.txt: key sk-secret',"
        " file=sys.stderr); sys.exit(1)"
    )
    assert str(error) == f"{Path(sys.executable).name} failed"  # the message is unchanged
    assert error.reason == "cannot attach notes.txt: key sk-***"
    # Nothing on stderr: its console's "Error: …" on stdout.
    error = _fails("import sys; print('\\x1b[31mError:\\x1b[0m no such task t_9'); sys.exit(2)")
    assert error.reason == "Error: no such task t_9"
    # Hermes's masking can't check it: nothing of it is shown.
    monkeypatch.setitem(hermes_redact._current, "redactor", None)
    assert _fails("import sys; sys.exit('cannot complete t_1')").reason == ""
    assert _fails("import sys; sys.exit(3)").reason == ""


def test_the_reason_keeps_hermess_words_and_cuts_paths() -> None:
    assert refusal_line(EMPTY.format("t_1"), "") == EMPTY.format("t_1")  # --result/--summary kept
    assert refusal_line("", "") == ""
    assert refusal_line("\n \n", "out line\n") == "out line"
    assert refusal_line("cannot read ~/.hermes/kanban.db, nor /srv/a/b.db.", "") == (
        "cannot read kanban.db, nor b.db."
    )
    assert refusal_line("see https://example.com/a/b and 1/2", "") == (
        "see https://example.com/a/b and 1/2"
    )
    assert len(refusal_line("x" * 900, "")) == 300
    assert refusal_line(hermes_redact.HIDDEN, "") == ""
