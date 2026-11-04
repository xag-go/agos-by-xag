"""The consent gate: an agent changes its own instruction files (SOUL.md,
config.yaml, AGENTS.md, profile.yaml) only through an approved `instructions`
proposal; the approved content passes exactly once (agos_guard/consent.py)."""

from __future__ import annotations

import hashlib
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from agos_core.hermes_plugin import agos_guard
from agos_core.hermes_plugin.agos_guard import consent

CONTENT = "# Editor\nI edit faster now.\n"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: Any) -> Path:
    """The agent's profile home, as Hermes tells the plugin (get_hermes_home)."""
    where = tmp_path / "profiles" / "a-editor"
    where.mkdir(parents=True)
    (where / "SOUL.md").write_text("# Editor\n")
    fake = types.ModuleType("hermes_constants")
    fake.get_hermes_home = lambda: str(where)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hermes_constants", fake)
    monkeypatch.setattr(agos_guard.policy, "_policy", lambda: {"member": "editor", "rules": {}})

    class Bridge:
        agent_of_session = staticmethod(lambda session: "editor")

    monkeypatch.setattr(agos_guard.runtime, "_bridge_module", lambda: Bridge)
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    return where


def _token(home: Path, content: str, *, consumed: bool = False, target: str = "SOUL.md") -> None:

    (home / consent.CONSENT_FILE).write_text(
        json.dumps(
            {
                "tokens": [
                    {
                        "card": "t_1",
                        "target": target,
                        "sha256": hashlib.sha256(content.encode()).hexdigest(),
                        "approved_at": "2026-10-26T00:00:00Z",
                        "consumed": consumed,
                    }
                ]
            }
        )
    )


def _verdict(tool: str, args: dict[str, Any]) -> dict[str, Any] | None:
    return agos_guard._verdict(tool, args, "s1")[0]


def test_without_a_token_every_way_to_its_own_files_is_refused(home: Path) -> None:
    soul = str(home / "SOUL.md")
    for tool, args in (
        ("write_file", {"path": soul, "content": CONTENT}),
        ("write_file", {"path": "SOUL.md", "content": CONTENT}),
        ("patch", {"path": soul, "old_string": "a", "new_string": "b"}),
        ("write_file", {"path": str(home / "config.yaml"), "content": "model: x"}),
        ("write_file", {"path": str(home / "AGENTS.md"), "content": "x"}),
        ("terminal", {"command": f"echo 'I rule' >> {soul}"}),
        ("terminal", {"command": f"sed -i 's/a/b/' {home}/config.yaml"}),
        ("terminal", {"command": "cat <<EOF > SOUL.md\nhi\nEOF"}),
        ("terminal", {"command": "cp /tmp/new.md $HERMES_HOME/profile.yaml"}),
        ("execute_code", {"code": f"open('{soul}', 'w').write('x')"}),
        ("skill_manage", {"name": "x", "action": "write_file", "file_path": "../../SOUL.md"}),
    ):
        verdict = _verdict(tool, args)
        assert verdict is not None and verdict["action"] == "block", (tool, args)
        assert "agos-proposal" in verdict["message"] and "instructions" in verdict["message"]
    # Reading them, and other files, is as before.
    assert _verdict("read_file", {"path": soul}) is None
    assert (
        _verdict("write_file", {"path": "/workspace/notes/SOUL-ideas.md", "content": "x"}) is None
    )
    assert _verdict("write_file", {"path": "/workspace/app/config.yaml", "content": "x"}) is None
    assert _verdict("terminal", {"command": "cat config.yaml > /tmp/copy.yaml"}) is None
    assert _verdict("terminal", {"command": f"cat {soul}"}) is None
    assert _verdict("terminal", {"command": "ls -la"}) is None


def test_the_approved_content_passes_once_then_the_token_is_consumed(home: Path) -> None:
    _token(home, CONTENT)
    soul = str(home / "SOUL.md")
    # Not the approved content: refused, the token stays.
    wrong = _verdict("write_file", {"path": soul, "content": CONTENT + "and more"})
    assert wrong is not None and "SHA-256" in wrong["message"]
    assert json.loads((home / consent.CONSENT_FILE).read_text())["tokens"][0]["consumed"] is False
    # patch / terminal can't be checked against the approved content: refused.
    assert _verdict("patch", {"path": soul, "old_string": "a", "new_string": "b"}) is not None
    assert _verdict("terminal", {"command": f"echo x > {soul}"}) is not None
    # The exact content: through, once.
    assert _verdict("write_file", {"path": soul, "content": CONTENT}) is None
    [token] = json.loads((home / consent.CONSENT_FILE).read_text())["tokens"]
    assert token["consumed"] is True
    again = _verdict("write_file", {"path": soul, "content": CONTENT})
    assert again is not None and again["action"] == "block"
    # A token for another file never opens this one.
    _token(home, CONTENT, target="config.yaml")
    assert _verdict("write_file", {"path": soul, "content": CONTENT}) is not None
    assert _verdict("write_file", {"path": str(home / "config.yaml"), "content": CONTENT}) is None


def test_the_gate_fails_open_only_when_the_home_is_unknown(monkeypatch: Any) -> None:
    monkeypatch.delitem(sys.modules, "hermes_constants", raising=False)
    import builtins

    real_import = builtins.__import__

    def no_hermes(name: str, *a: Any, **k: Any) -> Any:
        if name == "hermes_constants":
            raise ImportError("not inside Hermes")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_hermes)
    assert agos_guard.own_instructions("write_file", {"path": "SOUL.md", "content": "x"}) is None


def test_the_gate_is_part_of_the_hook_for_the_cofounder_too(home: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(
        agos_guard.policy, "_policy", lambda: {"rules": {}}
    )  # the Co-Founder's profile
    verdict = _verdict("write_file", {"path": str(home / "SOUL.md"), "content": "x"})
    assert verdict is not None and verdict["action"] == "block"
