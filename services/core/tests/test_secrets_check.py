"""The Secrets check on Settings → Health (ADR 0023): keys in chat history and logs
(Hermes's own masking decides, kind + last 4 only), wrong permissions; the
Co-Founder's for its own workspace only. Hermes's masking is stubbed (test_owner_keys
`_hermes_mask`); the real one scans a root where Hermes is installed (last test).
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import hermes_store
import pytest
from test_cofounder_hermes import _run
from test_library import env, ws  # noqa: F401 - fixture
from test_owner_keys import FAKE_KEY, _hermes_mask, _real_hermes

from agos_core.hermes_plugin.agos_guard import keys

# ---- the check --------------------------------------------------------------


def _in_process(monkeypatch: pytest.MonkeyPatch) -> None:
    from agos_core.actions import secrets_check

    monkeypatch.setattr(
        secrets_check, "_scan_root", lambda core, root: keys.scan(str(root), _hermes_mask)
    )


def _tidy(root: Path) -> None:
    """The fake runner's files with the modes Hermes gives them."""
    for path in root.rglob("*"):
        if path.is_file() and keys_secret(path.name):
            path.chmod(0o600)
    root.chmod(0o700)


def keys_secret(name: str) -> bool:
    from agos_core.actions import secrets_check

    return secrets_check._secret_file(name)


def test_the_secrets_check_finds_a_key_in_history_and_logs_and_a_wrong_mode(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, core, _runner, _home = env
    _in_process(monkeypatch)
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    for w in (a, b):
        _tidy(core.engine.root(w))
    for folder in (core.layout.root, core.layout.system):
        folder.chmod(0o700)
    for path in core.layout.root.rglob("*"):
        if path.is_file() and keys_secret(path.name):
            path.chmod(0o600)
    clean = client.post("/preferences/secrets-check")
    assert clean.status_code == 200, clean.text
    assert clean.json()["problems"] == 0, clean.json()
    root = core.engine.root(b)
    hermes_store.say(root, "c1", "user", f"use this key {FAKE_KEY}", source="telegram")
    hermes_store.title(root, "c1", "Keys talk", source="telegram")
    (root / "logs").mkdir(exist_ok=True)
    (root / "logs" / "agent.log").write_text(f"ok\nsent {FAKE_KEY}\nok\n")
    env_file = root / ".env"
    env_file.write_text("X=1\n")
    env_file.chmod(0o644)
    r = client.post("/preferences/secrets-check")
    assert r.status_code == 200, r.text
    assert FAKE_KEY not in r.text and FAKE_KEY[9:40] not in r.text
    found = r.json()
    [chat] = found["chats"]
    assert chat["workspaceId"] == b and chat["last4"] == "b1c2" and chat["kind"] == "sk-or-… key"
    assert (
        chat["session"] == "Keys talk" and chat["role"] == "user" and chat["source"] == "telegram"
    )
    [log] = found["logs"]
    assert log["file"] == "logs/agent.log" and log["count"] == 1
    assert {"path": str(env_file), "mode": "644", "want": "600"} in found["permissions"]
    assert found["problems"] == 3
    # The Co-Founder of each workspace sees its own findings only.
    [mine] = _run(core, b, {"do": "secrets_check"})
    assert mine["status"] == "done" and "b1c2" in mine["detail"] and "644" in mine["detail"]
    [theirs] = _run(core, a, {"do": "secrets_check"})
    assert theirs["detail"] == "Secrets check: 0 problems.", theirs["detail"]
    assert FAKE_KEY not in mine["detail"]


def test_a_folder_others_may_open_is_found(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    client, core, _runner, _home = env
    _in_process(monkeypatch)
    ws(client, "Alpha")
    core.layout.system.chmod(0o755)
    found = client.post("/preferences/secrets-check").json()
    assert {"path": str(core.layout.system), "mode": "755", "want": "700"} in found["permissions"]


def test_hermes_own_masking_finds_the_key_in_a_root_and_prints_no_value(tmp_path: Path) -> None:
    python = _real_hermes()
    if python is None:
        pytest.skip("no Hermes install on this machine")
    root = tmp_path / "agos-x"
    hermes_store.say(root, "c1", "user", f"key {FAKE_KEY}")
    hermes_store.say(root, "c1", "user", "call +212612345678")
    member = root / "profiles" / "a-writer"
    hermes_store.say(member, "c2", "assistant", "nothing secret here")
    done = subprocess.run(  # noqa: S603 - Hermes's runtime, AGOS's own file
        [python, str(Path(keys.__file__)), "scan", str(root)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    assert FAKE_KEY not in done.stdout and FAKE_KEY[9:40] not in done.stdout
    found = json.loads(done.stdout.split("AGOS-KEYS ", 1)[1])
    assert found["chats_total"] == 1
    [chat] = found["chats"]
    assert chat["last4"] == "b1c2" and chat["profile"] == "default"
    assert (
        sqlite3.connect(root / "state.db").execute("SELECT count(*) FROM messages").fetchone()[0]
        == 2
    )  # read only
