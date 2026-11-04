"""The Founder's task with the real Hermes (actions/founder.py): a card assigned to
`founder` the way AGOS makes it is never given a worker by Hermes's dispatcher (it
records skipped_nonspawnable and leaves it ready), AGOS's own read of the board finds
it with the card that waits on it, and his Done (Hermes's complete, AGOS's argv)
promotes that card. Skipped on a machine without Hermes; Hermes runs in a scratch
HOME and home of its own (its first command there prepares its dependencies, about
a minute), and the install's shared launcher must be left as it was."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from agos_core.actions import founder, kanban_board
from agos_core.engine.hermes import child_env

HERMES = shutil.which("hermes")
TOOLS = Path.home() / ".hermes" / "tools"
LAUNCHER = Path.home() / ".hermes" / "hermes-agent" / ".hermes" / "bin" / "hermes"

pytestmark = pytest.mark.skipif(not HERMES, reason="no Hermes install on this machine")


def test_a_founder_card_gets_no_worker_and_done_promotes_its_child(tmp_path: Path) -> None:
    home, root = tmp_path / "home", tmp_path / "root"
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

    try:
        body = founder.body_of("Record a 30 s intro.", "Friday")
        card = str(
            json.loads(
                cli(
                    "create",
                    "Record the intro",
                    "--json",
                    "--created-by",
                    "owner",
                    "--body",
                    body,
                    "--assignee",
                    founder.FOUNDER,
                )
            )["id"]
        )
        child = str(
            json.loads(
                cli("create", "Edit the intro", "--json", "--assignee", "default", "--parent", card)
            )["id"]
        )
        ticked = json.loads(cli("dispatch", "--json"))
        assert ticked["spawned"] == [] and card in ticked["skipped_nonspawnable"]
        shown = json.loads(cli("show", card, "--json"))
        assert shown["task"]["status"] == "ready"
        assert [e["kind"] for e in shown["events"]] == ["created", "skipped_nonspawnable"]
        ticked = json.loads(cli("dispatch", "--json"))  # a second tick: still nothing
        assert ticked["spawned"] == [] and ticked["reclaimed"] == 0 and ticked["stale"] == []
        # AGOS's own read of the board (read only).
        [row] = founder.rows_of(root / "kanban.db")
        assert (row["id"], row["status"], row["unblocks"]) == (card, "ready", [child])
        assert "By: Friday" in row["body"]
        # His Done: AGOS's complete argv; Hermes promotes the card waiting on it.
        cli(*kanban_board.complete_args(card, "Done by the founder."))
        assert json.loads(cli("show", child, "--json"))["task"]["status"] == "ready"
        [row] = founder.rows_of(root / "kanban.db")
        assert row["status"] == "done" and row["completedAt"]
    finally:
        if launcher is not None:
            assert LAUNCHER.read_bytes() == launcher, "a Hermes run rewrote the shared launcher"
        shutil.rmtree(tmp_path, ignore_errors=True)
