"""#56: whether a Telegram sender's mirrored /command is let in asks Hermes's own
public PairingStore.is_approved in the root (H: gateway/pairing.py, its id matching
included) for anyone not in the root's allowlist; no raw read of its pairing file.
Hermes not answering lets nobody new in."""

import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agos_core.actions import telegram_people
from agos_core.engine.hermes import _PAIRED, EngineError


class _Engine:
    def __init__(self, home: Path, answer: Any) -> None:
        self.home, self.answer = home, answer
        self.asked: list[Any] = []

    def profile_home(self, workspace_id: str) -> Path:
        return self.home

    def pairing_approved(self, home: Path, platform: str, user_id: str) -> bool:
        self.asked.append((home, platform, user_id))
        if isinstance(self.answer, Exception):
            raise self.answer
        return bool(self.answer)


def _core(tmp_path: Path, answer: Any, allow: str = "") -> Any:
    home = tmp_path / "root"
    home.mkdir(parents=True)
    (home / ".env").write_text(f"TELEGRAM_ALLOWED_USERS={allow}\n" if allow else "")
    return SimpleNamespace(engine=_Engine(home, answer))


def test_a_paired_sender_is_hermess_own_answer(tmp_path: Path) -> None:
    core = _core(tmp_path, True)
    assert telegram_people.lets_in(core, "ws", "555")
    assert core.engine.asked == [(core.engine.home, "telegram", "555")]


def test_the_allowlist_needs_no_question(tmp_path: Path) -> None:
    core = _core(tmp_path, False, allow="111,222")
    assert telegram_people.lets_in(core, "ws", "222") and core.engine.asked == []
    assert not telegram_people.lets_in(core, "ws", "333")
    star = _core(tmp_path / "s", False, allow="*")
    assert telegram_people.lets_in(star, "ws", "9") and star.engine.asked == []


def test_hermes_not_answering_lets_nobody_new_in(tmp_path: Path) -> None:
    core = _core(tmp_path, EngineError("Hermes didn't answer"))
    assert not telegram_people.lets_in(core, "ws", "555")


def test_lets_in_reads_no_pairing_file() -> None:
    src = inspect.getsource(telegram_people.lets_in)
    assert "_approved(home)" not in src and " ids(core" not in src
    assert "PairingStore" in _PAIRED and ".is_approved(" in _PAIRED


@pytest.mark.parametrize("uid", [""])
def test_no_sender_is_no(tmp_path: Path, uid: str) -> None:
    assert not telegram_people.lets_in(_core(tmp_path, True), "ws", uid)
