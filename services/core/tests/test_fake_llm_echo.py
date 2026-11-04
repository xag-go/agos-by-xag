"""The e2e fake model's DM answer keeps the owner's words even on a first message.

On a workspace's very first message Hermes adds a long note after the owner's text; an
echo of only the last 300 characters then missed his words (the stranger-install VM check
saw "no fake-model answer" although the Co-Founder had answered).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

FAKE_LLM = Path(__file__).resolve().parent / "e2e" / "fake_llm.py"


def _fake_llm() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fake_llm_echo_probe", FAKE_LLM)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _answer(prompt: str) -> str:
    got = _fake_llm().decide([{"role": "user", "content": prompt}])
    return str(got["text"])


def test_a_first_message_answer_still_holds_the_owners_words() -> None:
    note = "[System note: this is the first message of this workspace. " + "x" * 800 + "]"
    text = _answer("[Wed 17:01] hello from a stranger\n\n" + note)
    assert text.startswith("DM answer: ")
    assert "hello from a stranger" in text
    assert text.endswith("x" * 200 + "]")


def test_a_short_message_is_echoed_whole() -> None:
    assert _answer("[Wed 17:01] hi there") == "DM answer: [Wed 17:01] hi there"
