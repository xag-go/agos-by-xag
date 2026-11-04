"""Live: an automation fires on schedule in the workspace's real Hermes cron.

AGOS_LIVE_AUTOMATIONS=1 against a running core (real engine). One throwaway
workspace; the automation runs every minute; the test waits for a scheduled
(not manual) run to come back into AGOS, then removes everything.
"""

import json
import os
import secrets
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("AGOS_LIVE_AUTOMATIONS") != "1", reason="live test (AGOS_LIVE_AUTOMATIONS=1)"
)

CORE = os.environ.get("AGOS_CORE_URL", "http://127.0.0.1:8766")
if not CORE.startswith(("http://", "https://")):
    raise ValueError("AGOS_CORE_URL must be http(s)")
DATA = Path(os.environ.get("AGOS_DATA_DIR", "agos-data"))
HERMES = Path(os.environ.get("HERMES_HOME_ROOT", str(Path.home() / ".hermes")))
MODEL = {"provider": "claude", "mode": "cli", "model": "claude-sonnet-5", "effort": "low"}


def call(method: str, path: str, body: Any = None, timeout: float = 120) -> Any:
    token = (DATA / "system" / "internal.token").read_text().strip()
    req = urllib.request.Request(  # noqa: S310 - http(s) only, checked above
        CORE + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"x-agos-internal": token, "content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        raw = r.read()
        return json.loads(raw) if raw else None


def test_automation_fires_on_schedule_and_reports_back() -> None:
    tag = secrets.token_hex(3)
    ws = call(
        "POST",
        "/workspaces",
        {"name": f"zz-live-{tag}-cron", "description": "Automation probe.", "defaultModel": MODEL},
    )["id"]
    try:
        aid = call(
            "POST",
            f"/workspaces/{ws}/automations",
            {
                "name": "Minute probe",
                "instructions": f"Write the line PROBE-{tag}, then propose exactly one card "
                'titled "Probe card" with your kanban_create tool.',
                "schedule": "* * * * *",
                "model": MODEL,
                "on": True,
            },
        )["id"]
        listed = call("GET", f"/workspaces/{ws}/automations")[0]
        assert listed["problem"] is None, listed["problem"]
        jobs = json.loads((DATA / "hermes" / f"agos-{ws}" / "cron" / "jobs.json").read_text())
        (job,) = [j for j in (jobs["jobs"] if isinstance(jobs, dict) else jobs)]
        assert job["model"] == "claude-sonnet-5" and job["reasoning_effort"] == "low"
        deadline = time.monotonic() + 300
        runs: list[dict[str, Any]] = []
        while time.monotonic() < deadline and not runs:
            time.sleep(10)
            runs = call("GET", f"/workspaces/{ws}/automations/{aid}/runs")
        assert runs, "no run within 5 minutes"
        run = runs[0]
        print("run:", json.dumps(run)[:600])
        assert run["result"] == "ok", run
        assert run["source"] == "schedule"  # fired by the schedule, not by hand
        assert f"PROBE-{tag}" in run["report"]
        print("report:", run["report"][:800])
        # The card waits on the board for the owner (Hermes's own Kanban).
        assert [(p["title"], bool(p["kanbanCard"])) for p in run["proposals"]] == [
            ("Probe card", True)
        ]
        # Turning it off pauses the Hermes job.
        call("POST", f"/workspaces/{ws}/automations/{aid}/toggle", {"on": False})
        jobs = json.loads((DATA / "hermes" / f"agos-{ws}" / "cron" / "jobs.json").read_text())
        (job,) = [j for j in (jobs["jobs"] if isinstance(jobs, dict) else jobs)]
        assert job["enabled"] is False
    finally:
        try:
            call("POST", f"/workspaces/{ws}/delete", {"confirm": ws})
            call("DELETE", f"/trash/{ws}")
        except urllib.error.HTTPError as error:
            print("cleanup", ws, error.code, error.read()[:200])
