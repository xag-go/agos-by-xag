"""The light rig the browser tests click on: AGOS's real core and HTTP API with the test
suite's fake Hermes (tests/work_env.py `env`, tests/fake_gateway.py), served by uvicorn
on a real port so the real web build can talk to it. No Hermes, no Docker, no model:
it runs on a GitHub runner.

Run (the browser tests' `rig` fixture does it, tests/browser/rig.py):

    AGOS_LIGHT_PORT=9611 AGOS_LIGHT_STATE=<file> pytest -q -s -p no:cacheprovider \
        tests/browser/serve_light.py

It is a "test" only to borrow the suite's fixtures (the autouse fakes of Hermes's
profile writes, the fake board): it seeds one workspace, writes the state file (data
dir, token file, workspace ids) and then serves until it is killed. A thread plays the
workspace's gateway: it takes AGOS's inbox and answers each owner message after a
short think ("Fake answer: <his words>").
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fake_gateway import pump
from test_automations import FakeCron
from work_env import (  # noqa: F401 - fixtures used by name
    Env,
    create_ws,
    env,
    fake_board,
    fake_models,
)

from agos_core.actions import remote_access, today
from agos_core.engine import sandbox_broker
from browser.seed import seed

# Settings → Access asks this machine for its `tailscale` command: installed here, not
# on a CI runner, so the card would differ by machine. The rig says "installed, not
# activated" (the "off" card) everywhere; nothing runs it (no flow presses Activate:
# a call would fail on the missing file, never reach a real Tailscale).
FAKE_TAILSCALE = "/nonexistent/agos-light-rig/tailscale"
# The owner's "today" on the rig: the day the screen baselines were drawn. Pages count
# from it (Vision's "58 days" to the seeded goal's 2026-12-31), so a real date would
# change a baseline every midnight.
LIGHT_TODAY = os.environ.get("AGOS_LIGHT_TODAY", "2026-11-03")

# How long the fake model "thinks" before it answers: long enough for the page to show
# the answer in progress, short enough for a click test.
THINK_S = float(os.environ.get("AGOS_LIGHT_THINK_S", "1.5"))


def _answers(fake: Any, core: Any, stop: threading.Event) -> None:
    """The workspace's gateway: takes AGOS's inbox and answers what it was asked."""
    started: dict[str, float] = {}
    while not stop.is_set():
        try:
            pump(core, fake)
            now = time.monotonic()
            for run_id, run in list(fake.runs.items()):
                if run.get("status") != "running":
                    continue
                first = started.setdefault(run_id, now)
                if now - first >= THINK_S:
                    asked = _asked(fake, run_id)
                    fake.finish(run_id, f"Fake answer: {asked}" if asked else "Fake answer.")
            pump(core, fake)
        except Exception as error:  # noqa: BLE001 - the rig keeps serving; the test sees the page
            print("light rig gateway round failed:", type(error).__name__, error, flush=True)
        stop.wait(0.3)


def _asked(fake: Any, run_id: str) -> str:
    """The owner's words of one answer (the fake gateway's body for that run)."""
    index = int(run_id.rsplit("_", 1)[-1]) - 1
    bodies: list[dict[str, Any]] = fake.bodies
    if not 0 <= index < len(bodies):
        return ""
    body = bodies[index]
    text = str(body.get("input") or body.get("text") or body.get("message") or "")
    return " ".join(text.split())[-200:]


def test_serve(env: Env, fake_board: None, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    port = int(os.environ.get("AGOS_LIGHT_PORT", "9611"))
    state_file = Path(os.environ.get("AGOS_LIGHT_STATE", "light-rig.json"))
    client, fake, core, ws = env
    fake_models(monkeypatch)
    monkeypatch.setattr(remote_access, "tailscale_bin", lambda: FAKE_TAILSCALE)
    monkeypatch.setattr(today, "date_today", lambda core=None: LIGHT_TODAY)
    # The owner's machine: every gateway caged (the cage is required by default). The
    # rig's fake engine has no cage at all, which Settings -> Server & backup would
    # report as "isolation OFF"; the screens show the owner's caged page.
    monkeypatch.setattr(sandbox_broker, "state", lambda engine: "ok")
    # Hermes's cron (the automations' jobs), as the automation tests fake it.
    cron = FakeCron()
    cron.runner = core.engine.runner
    core.engine.cron_bridge = cron
    seeded = seed(client, core, ws)
    # A second workspace for the click tests: what they change never shows in the screens.
    flows = create_ws(client, "Flows")
    flows_seeded = seed(client, core, flows)
    stop = threading.Event()
    gateway = threading.Thread(target=_answers, args=(fake, core, stop), daemon=True)
    gateway.start()
    settings = core.settings
    state = {
        "core": f"http://127.0.0.1:{port}",
        "data_dir": str(settings.data_dir),
        "token_file": str(settings.internal_token_file),
        "workspace": ws,
        "seed": seeded,
        "flows": flows,
        "flows_seed": flows_seeded,
    }
    tmp = state_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(state_file)
    print("LIGHT-RIG-READY", json.dumps(state), flush=True)
    try:
        uvicorn.run(client.app, host="127.0.0.1", port=port, lifespan="off", log_level="warning")
    finally:
        stop.set()
