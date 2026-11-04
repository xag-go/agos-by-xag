"""Each workspace's root gateway runs the way Hermes runs itself.

A workspace's root has one gateway (ADR 0020): its Co-Founder, every team member
(Hermes multiplexing), its bot, scheduler, heartbeat, Kanban dispatcher and group
rooms live inside it, always on. Hermes's own systemd service (`hermes gateway
install`: Restart=always, started at login) keeps it up and restarts it after a
crash. AGOS does one pass when it starts (`ensure_all`) and one when a workspace
comes back from the archive or the trash (`ensure`): it installs that service, or
hands a gateway it started earlier over to it. Nothing in AGOS watches the
gateways afterwards. With the "spawn" supervisor (throwaway roots in tests and e2e
runs) the pass starts the process itself. Members have no lifecycle of their own.
"""

from __future__ import annotations

import logging

from agos_core.context import Core
from agos_core.engine.hermes import EngineError

log = logging.getLogger("agos.idle")


def ensure(core: Core, workspace_id: str) -> bool:
    """The workspace's gateway runs as Hermes's service (installed, or a gateway
    AGOS started earlier handed over to it). True when AGOS started something."""
    engine = core.engine
    if engine is None:
        return False
    try:
        if engine.service_active(workspace_id):
            return False
        if engine.settings.gateway_supervisor == "spawn" and engine.is_running(workspace_id):
            return False
        engine.start(workspace_id)
    except (EngineError, OSError):
        return False
    except ValueError as error:  # an id the engine refuses (it runs in a thread: never raise)
        log.warning("workspace %r: gateway not started (%s)", workspace_id, error)
        return False
    log.info("the Co-Founder of %s runs as Hermes's gateway", workspace_id)
    return True


def spawned_up(core: Core, workspace_id: str) -> bool:
    """Under the test-only "spawn" supervisor (no Hermes service to restart it) a
    gateway AGOS spawned is started again when work arrives for it. Under Hermes's
    own systemd service nothing: `Restart=always` (H: hermes_cli/gateway.py, the unit
    `hermes gateway install` writes) does it, and a gateway the owner or AGOS
    stopped on purpose stays stopped. True when AGOS started one."""
    engine = core.engine
    if engine is None or engine.settings.gateway_supervisor != "spawn":
        return False
    try:
        if engine.is_running(workspace_id):
            return False
        engine.start(workspace_id)
        return True
    except Exception as error:  # noqa: BLE001 — the inbox waits; the plugin takes it later
        log.warning("workspace %s: gateway not started (%s)", workspace_id, error)
        return False


def ensure_all(core: Core) -> list[str]:
    """One pass when AGOS starts: every active workspace's gateway runs as Hermes's
    service. Returns the workspaces it started."""
    if core.engine is None:
        return []
    rows = core.db.execute(
        "SELECT id FROM workspaces WHERE deleted_at IS NULL AND archived_at IS NULL"
    ).fetchall()
    return [str(row["id"]) for row in rows if ensure(core, str(row["id"]))]


def chores(core: Core) -> None:
    """AGOS's own small chores, one round (the "idle.chores" job, every minute:
    agos_core/background/schedule.py). No gateway watching: that is Hermes's service."""
    if core.engine is None:
        return
    from agos_core.actions import hermes_channel

    hermes_channel.tidy_inbox(core)
    # A turn Hermes answered without its agent (no AI login) never reports
    # back: closed once Hermes's own status says it answers nothing.
    hermes_channel.close_unanswered(core)
    from agos_core.actions import apps

    # Composio: a session follows its project's user once the owner connects
    # a first app in Composio (so the agent sees those apps).
    apps.follow_composio_users(core)
