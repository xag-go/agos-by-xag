"""The owner's "Daily digest" (Settings → Notifications, `batched`): AGOS's own
phone cards for that event are held and go out once a day, in one message.

- Instant: the card goes to the phone at once (as before).
- Daily digest: nothing on the phone now; the chat in AGOS still shows it. Once a
  day at `HOUR` in the owner's timezone, one message lists what was held, in the
  Co-Founder's Telegram place.
- Silent: nothing on the phone.

Who does what:
- The held lines are AGOS's own card data (`digest.held.<ws>`). Hermes has nothing
  to batch these: its notification batching is only a 0.1 s window for background
  completions (H: gateway/run_notifications.py).
- The clock and the delivery are Hermes's. Each workspace's root has one no-agent
  cron job (`JOB`): Hermes runs `SCRIPT` at `SCHEDULE`, in the owner's `timezone`
  (H: cron/jobs.py uses hermes_time). The script takes the held lines from AGOS
  (`/hermes-bridge/<ws>/digest`) and prints them. Hermes delivers that stdout
  verbatim, with no model call and no tokens, to the job's `--deliver` target: the
  Co-Founder's Telegram chat or topic. Empty stdout is a silent run
  (H: cron/scheduler.py `_run_no_agent_job`). Hermes's cron delivery puts its own
  header and footer around it (`cron.wrap_response`, Hermes's default, left as it
  is).
- `keep_job` makes the job when an event is on Daily digest and the Co-Founder has a
  Telegram place. It points the job at that place when the place changes, and
  removes the job when nothing is batched any more. It runs when the owner
  changes the setting, when a line is held, and once at AGOS's start.
"""

from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Any

from agos_core.context import Core
from agos_core.db.app_settings import get_setting, set_setting
from agos_core.db.rows import now
from agos_core.hermes_gateway import cli as hermes_cli

log = logging.getLogger("agos.digest")

HOUR = 9  # the owner's morning
SCHEDULE = f"0 {HOUR} * * *"  # Hermes's cron, in the owner's timezone
KEEP = 50  # lines in one digest (the oldest go)
HELD = "digest.held."  # + workspace id: what waits for the next digest
JOB = "agos-digest"  # the Hermes cron job's name in each root (not an agent's job)
SCRIPT = "agos-digest.py"  # in the root's Hermes scripts folder

# Run by Hermes's cron (no agent): the held lines from AGOS, printed for Hermes to
# deliver. Standard library only (Hermes runs it with its own Python).
SCRIPT_TEXT = r'''"""AGOS's Daily digest: Hermes's cron delivers what this prints (no agent)."""
import json
import sys
import urllib.request
from pathlib import Path

home = Path(__file__).resolve().parent.parent  # <home>/scripts/agos-digest.py
bridge = json.loads((home / "agos-bridge.json").read_text())
core = str(bridge["core"]).rstrip("/")
if not core.startswith(("http://127.0.0.1", "http://localhost")):
    sys.exit(0)  # AGOS's core is on this machine, nowhere else
request = urllib.request.Request(
    f"{core}/hermes-bridge/{bridge['workspace']}/digest",
    data=b"{}",
    headers={"content-type": "application/json", "authorization": f"Bearer {bridge['key']}"},
    method="POST",
)
with urllib.request.urlopen(request, timeout=30) as reply:
    answer = json.loads(reply.read() or b"{}")
sys.stdout.write(str(answer.get("text") or ""))
'''


def batched(core: Core, event: str) -> bool:
    from agos_core.actions.notification_rules import delivery_for

    return delivery_for(core, event) == "batched"


def any_batched(core: Core) -> bool:
    from agos_core.actions.notification_rules import EVENTS

    return any(batched(core, e) for e in EVENTS)


def hold(core: Core, workspace_id: str, event: str, text: str) -> None:
    """One line for the next digest instead of a card on the phone now."""
    held = _held(core, workspace_id)
    held.append({"at": now(), "event": event, "text": " ".join(text.split())[:300]})
    set_setting(core.db, HELD + workspace_id, held[-KEEP:])
    keep_job_soon(core, workspace_id)


def _held(core: Core, workspace_id: str) -> list[dict[str, Any]]:
    value = get_setting(core.db, HELD + workspace_id, [])
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def take(core: Core, workspace_id: str) -> str:
    """The digest Hermes's job delivers now: the held lines in one message (they
    are gone from AGOS once taken). "" = nothing held (a silent run)."""
    held = _held(core, workspace_id)
    core.db.execute("DELETE FROM app_settings WHERE key = ?", (HELD + workspace_id,))
    lines = [f"• {h['text']}" for h in held if h.get("text")]
    return ("🗞 **Daily digest**\n" + "\n".join(lines)) if lines else ""


# ---- the Hermes cron job ---------------------------------------------------------


def deliver_to(core: Core, workspace_id: str) -> str | None:
    """Hermes's delivery target for the digest: the Co-Founder's Telegram place (its
    chat, or chat:topic), as AGOS's phone cards go (owner_needs.targets)."""
    from agos_core.actions import hermes_channel
    from agos_core.actions.services.channel import owner_needs

    for _connection, address in owner_needs.targets(core, workspace_id):
        chat, _, thread = hermes_channel.address_of(address).partition(":")
        if chat:
            return f"telegram:{chat}" + (f":{thread}" if thread not in ("", "0") else "")
    return None


def _job(home: Path) -> dict[str, Any] | None:
    """The digest job as Hermes saved it (the root's cron/jobs.json, read only)."""
    import json

    try:
        data = json.loads((home / "cron" / "jobs.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    jobs = data.get("jobs") if isinstance(data, dict) else data
    if isinstance(jobs, dict):
        jobs = [{**v, "id": v.get("id") or k} for k, v in jobs.items() if isinstance(v, dict)]
    return next(
        (j for j in jobs or [] if isinstance(j, dict) and j.get("id") and j.get("name") == JOB),
        None,
    )


def _write_script(home: Path) -> None:
    scripts = home / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    path = scripts / SCRIPT
    try:
        if path.read_text() == SCRIPT_TEXT:
            return
    except OSError:
        pass
    tmp = path.with_suffix(".tmp")
    tmp.write_text(SCRIPT_TEXT)
    tmp.chmod(0o600)
    tmp.replace(path)


def keep_job(core: Core, workspace_id: str) -> str:
    """The workspace's digest job in Hermes's cron matches the owner's choice.
    Returns what was done: "made", "moved", "removed" or ""."""
    from agos_core.engine.hermes import EngineError

    engine = core.engine
    if engine is None or engine.not_migrated(workspace_id):
        return ""
    home = engine.root(workspace_id)
    if not (home / "config.yaml").is_file():
        return ""
    target = deliver_to(core, workspace_id) if any_batched(core) else None
    job = _job(home)
    try:
        if target is None:
            if job is None:
                return ""
            hermes_cli.cli(engine, workspace_id, "cron", "remove", str(job["id"]))
            return "removed"
        _write_script(home)
        if job is None:
            said = hermes_cli.cli(
                engine,
                workspace_id,
                "cron",
                "create",
                f"--name={JOB}",
                f"--deliver={target}",
                "--failure-deliver=local",
                f"--script={SCRIPT}",
                "--no-agent",
                "--",
                SCHEDULE,
                timeout=120,
            )
            if not re.search(r"Created job: (\S+)", said or ""):
                log.warning("digest job not made in %s: %s", workspace_id, (said or "")[-200:])
                return ""
            return "made"
        if str(job.get("deliver") or "") != target:
            hermes_cli.cli(
                engine, workspace_id, "cron", "edit", str(job["id"]), f"--deliver={target}"
            )
            return "moved"
    except (EngineError, OSError) as error:
        log.warning("digest job of %s not kept: %s", workspace_id, error)
    return ""


def keep_job_soon(core: Core, workspace_id: str) -> None:
    """keep_job off the request (one Hermes CLI call when something changes)."""

    def run() -> None:
        try:
            keep_job(core, workspace_id)
        except Exception:
            log.exception("digest job of %s not kept", workspace_id)

    threading.Thread(target=run, name=f"digest-{workspace_id}", daemon=True).start()


def keep_all(core: Core) -> int:
    """Every active workspace (AGOS's start, his Notifications change). Lines
    held before the job existed stay held and go with its first run."""
    rows = core.db.execute(
        "SELECT id FROM workspaces WHERE deleted_at IS NULL AND archived_at IS NULL"
    ).fetchall()
    return sum(1 for r in rows if keep_job(core, str(r["id"])))


def job_ids(core: Core, workspace_id: str) -> set[str]:
    """The digest job's id (AGOS's, not an agent's: Ongoing leaves it out)."""
    if core.engine is None:
        return set()
    job = _job(core.engine.profile_home(workspace_id))
    return {str(job["id"])} if job else set()
