"""A team member's Revisions tab (Step 56, F08): every change AGOS writes into the
member's Hermes profile (its SOUL.md role text and the owner's notes, profile.yaml
title / description / lead, config model and skills, its heartbeat job) appends a
revision with who made it and why (db/agent_revisions.py keeps them).

- The writers call `record` after their write (team.save, set_on, set_reports_to,
  heartbeat.set_heartbeat); who/why come from the caller's `by(...)` (the owner by
  default, the Co-Founder's action cards, an import or a ready-made team).
- A change that didn't come through AGOS (an agent writing its own SOUL.md after
  the owner approved its instructions proposal, a hand edit) shows as a revision by
  "hermes" the next time the tab is read.
- Restore = a new write of revision vN through the team's own path (team.save,
  team.park, the heartbeat toggle), recorded as "restored from vN". The consent
  rule of Step 43 holds: a member never changes its own instructions by itself, so
  a restore asked by the member itself becomes an instructions proposal the owner
  approves in his Inbox (actions/proposals.py), never a write.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.context import Core
from agos_core.db import agent_revisions as revisions
from agos_core.db.activity import add_activity
from agos_core.db.records import AgentRevision

log = logging.getLogger("agos.agent_revisions")

OUTSIDE = "hermes"
OUTSIDE_WHY = "changed outside AGOS (an approved instructions proposal or a hand edit)"
FIRST_WHY = "how it was before revisions were kept"
_BY: ContextVar[tuple[str, str]] = ContextVar("agos_agent_revision_by", default=("owner", ""))


@contextlib.contextmanager
def by(who: str, why: str = "") -> Iterator[None]:
    """Every member write inside is recorded as made by `who`, for `why`."""
    token = _BY.set((who, why))
    try:
        yield
    finally:
        _BY.reset(token)


def _heartbeat(core: Core, workspace_id: str, name: str, before: str | None) -> str | None:
    """The member's heartbeat interval ("" off); `before` when Hermes's cron can't
    be read now (a revision never says it changed because a read failed)."""
    from agos_core.actions import heartbeat
    from agos_core.engine.cron import CronError
    from agos_core.engine.hermes import EngineError

    try:
        _home, jobs = heartbeat._home_and_jobs(core, workspace_id, name)
    except (CronError, EngineError, ActionError, OSError, ValueError):
        return before  # an unreadable cron keeps what the last revision said
    job = heartbeat._job_of(jobs)
    if job is None:
        return ""
    shown = heartbeat._view(name, job)
    return shown.interval or "custom" if shown.on else ""


def heartbeat_of(core: Core, workspace_id: str, name: str) -> str:
    """The member's heartbeat interval, "" when off (or unreadable)."""
    return _heartbeat(core, workspace_id, name, None) or ""


def _snapshot(core: Core, workspace_id: str, name: str, last: dict[str, Any] | None) -> Any:
    from agos_core.actions import team

    agent = team.get(core, workspace_id, name)
    if agent is None:
        return None
    beat = _heartbeat(core, workspace_id, name, (last or {}).get("heartbeat"))
    return revisions.snapshot_of(agent, beat)


def catch_up(core: Core, workspace_id: str, name: str) -> None:
    """Before a write (and before the tab is read): the member as it is now, when
    that is not the last revision. The first time, that is how it was before
    revisions were kept ("earlier"); later, a change made outside AGOS ("hermes")."""
    try:
        last = revisions.latest_snapshot(core.db, workspace_id, name)
        now = _snapshot(core, workspace_id, name, last)
        if now is None:
            return
        revisions.append(
            core.db,
            workspace_id,
            name,
            now,
            who="earlier" if last is None else OUTSIDE,
            why=FIRST_WHY if last is None else OUTSIDE_WHY,
        )
    except Exception:
        log.exception("revision of %s in %s not kept", name, workspace_id)


def record(
    core: Core,
    workspace_id: str,
    name: str,
    *,
    restored_from: int | None = None,
    who: str | None = None,
    why: str | None = None,
) -> int | None:
    """After a write: the member as it is now, as a revision by whoever `by` names
    (only when something changed, or on a restore). Never raises: a revision that
    can't be kept never undoes the write it follows."""
    said_who, said_why = _BY.get()
    try:
        last = revisions.latest_snapshot(core.db, workspace_id, name)
        now = _snapshot(core, workspace_id, name, last)
        if now is None:
            return None
        return revisions.append(
            core.db,
            workspace_id,
            name,
            now,
            who=who or said_who,
            why=why if why is not None else said_why,
            restored_from=restored_from,
        )
    except Exception:
        log.exception("revision of %s in %s not kept", name, workspace_id)
        return None


def list_for(core: Core, workspace_id: str, name: str) -> list[AgentRevision]:
    """The member's revisions, newest first. A change made outside AGOS since the
    last one is recorded first (who: hermes)."""
    from agos_core.actions import team

    if team.get(core, workspace_id, name) is None:
        raise NotFoundError("This agent")
    catch_up(core, workspace_id, name)
    return revisions.list_revisions(core.db, workspace_id, name)


def _own_restore(core: Core, workspace_id: str, name: str, n: int, snap: dict[str, Any]) -> Any:
    """The member asked to go back to vN itself: an instructions proposal (the
    whole SOUL.md that revision makes, its diff and SHA-256), never a write."""
    import difflib

    from agos_core.actions import agent_profiles, proposals, team

    agent = team.get(core, workspace_id, name)
    assert agent is not None and core.engine is not None
    if str(snap.get("instructions") or "") == agent.instructions:
        raise ActionError("Only the role text can be proposed back; nothing else changes.", 409)
    home = core.engine.profile_home(agent_profiles.key(workspace_id, name))
    try:
        current = (home / "SOUL.md").read_text(encoding="utf-8")
    except OSError:
        current = ""
    wanted = agent_profiles.soul_text(
        core,
        workspace_id,
        title=agent.title,
        instructions=str(snap.get("instructions") or ""),
        local=agent.local,
        reads=agent.reads,
        agent=name,
    )
    diff = "".join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            wanted.splitlines(keepends=True),
            "SOUL.md",
            "SOUL.md",
        )
    )
    return proposals.propose(
        core,
        workspace_id,
        "instructions",
        {
            "target": "SOUL.md",
            "diff": diff,
            "sha256": hashlib.sha256(wanted.encode()).hexdigest(),
            "summary": f"Restore my role text to v{n}",
        },
        member=name,
        by_tool=True,
    )


def restore(core: Core, workspace_id: str, name: str, n: int, who: str = "owner") -> dict[str, Any]:
    """Back to revision vN: a new write through the team's own path, recorded as
    "restored from vN". `who` is the member itself: an instructions proposal."""
    from agos_core.actions import heartbeat, team

    agent = team.get(core, workspace_id, name)
    if agent is None:
        raise NotFoundError("This agent")
    snap = revisions.get_snapshot(core.db, workspace_id, name, n)
    if snap is None:
        raise NotFoundError(f"Revision v{n}")
    if who in (name, f"@{name}"):
        return {"proposed": True, **_own_restore(core, workspace_id, name, n, snap)}
    catch_up(core, workspace_id, name)
    definition = {
        "instructions": str(snap.get("instructions") or ""),
        "model": snap.get("model") if isinstance(snap.get("model"), dict) else None,
        "skills": [str(s) for s in snap.get("skills") or []],
        "reads": list(snap.get("reads") or []),
        "reports_to": str(snap.get("reports_to") or ""),
    }
    with by(who, f"restored from v{n}"):
        team.save(
            core,
            workspace_id,
            name,
            title=str(snap.get("title") or agent.title),
            summary=str(snap.get("summary") or ""),
            definition=definition,
            new=False,
            local=str(snap.get("local") or ""),
            record_revision=False,
        )
        if bool(snap.get("on", True)) != agent.on:
            team.park(core, workspace_id, name, not bool(snap.get("on", True)))
        beat = str(snap.get("heartbeat") or "")
        if beat != str(_heartbeat(core, workspace_id, name, beat) or ""):
            with contextlib.suppress(ActionError):
                heartbeat.set_heartbeat(
                    core,
                    workspace_id,
                    name,
                    on=bool(beat),
                    interval=beat if beat in heartbeat.INTERVALS else "1h",
                    record_revision=False,
                )
    made = record(core, workspace_id, name, restored_from=n, who=who, why=f"restored from v{n}")
    add_activity(core.db, workspace_id, kind="agent.restored", text=f"@{name} restored from v{n}")
    return {"proposed": False, "n": made}
