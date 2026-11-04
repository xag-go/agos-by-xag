"""A staging copy of AGOS (`agos staging`, AGOS_STAGING=1): quiet by design.

The copy runs on a restore of live's newest backup beside live. It must never
act in the owner's name, so:
- every Hermes cron job of every staging workspace is paused with `REASON`
  (Hermes's own `hermes cron pause`), at start and again every ops-watch pass, so a
  job AGOS (re)creates is caught too; nothing in AGOS resumes a job paused with
  this reason;
- AGOS's own automation and channel loops don't start (no card-move rules, no
  Telegram outbox), and no phone push is sent (web_push.notify);
- a backup holds no key (ADR 0023), so the copy has no bot token: Hermes polls no
  Telegram bot. Keys entered in the copy are the copy's own.
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("agos.staging")

REASON = "Staging copy of AGOS: automations are off here"


def on() -> bool:
    return os.environ.get("AGOS_STAGING", "") == "1"


def quiet(core: Any) -> int:
    """Pauses every running Hermes cron job of every workspace; returns how many."""
    if not on() or core.engine is None:
        return 0
    from agos_core.actions import automations as automation_actions
    from agos_core.engine.cron import CronError, read_jobs
    from agos_core.engine.hermes import EngineError

    bridge = automation_actions.cron_bridge(core)
    if bridge is None:
        return 0
    paused = 0
    for row in core.db.execute("SELECT id FROM workspaces WHERE deleted_at IS NULL").fetchall():
        for agent, home in automation_actions.homes(core, str(row["id"])).items():
            if not (home / "config.yaml").is_file():
                continue
            custom = getattr(core.engine, "cron_bridge", None)
            try:
                jobs = custom.job_states(home) if custom is not None else read_jobs(home)
            except (CronError, OSError, ValueError) as error:
                log.warning("staging: cron of %s not read: %s", agent or "Co-Founder", error)
                continue
            for job in jobs:
                if not job.get("enabled"):
                    continue
                try:
                    bridge.pause(home, str(job["id"]), REASON)
                    paused += 1
                except (CronError, EngineError, OSError) as error:
                    log.warning("staging: job %s not paused: %s", job.get("id"), error)
    if paused:
        log.info("staging: %d Hermes cron job(s) paused", paused)
    return paused
