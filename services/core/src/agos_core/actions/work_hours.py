"""Work hours of a workspace (Settings → Work hours): check-in / check-out like a
company, so nothing works off-hours unless the owner says so.

The owner sets one week for the whole workspace (each day from HH:MM to HH:MM, an
overnight range ends the next morning, or OFF) on the owner's clock (General →
timezone, Hermes's own `timezone`; empty = UTC). Off by default: a workspace that
never turned it on runs always, as before. "Who stays on today" picks agents
(members and/or the Co-Founder) that keep working until the next check-in; the pick
clears itself then (its end is stored with it). "Wake now" in a chat is that pick.

Hermes has no work hours of its own (no quiet / working hours in its cron, gateway or
Kanban dispatcher; its ESTOP pause is all-or-nothing for a root and answers new
turns with "Hermes is paused", agent/estop.py paused_reply), so AGOS drives Hermes's
own switches per agent, from its automation loop (`keep`, once a minute):

- dispatcher: an agent that is off is left out of the root's
  `kanban.dispatch_profiles` (agent_profiles.dispatch_list, the way a member whose
  Readiness isn't done is held): Hermes spawns no worker for it
  (hermes_cli/kanban_db_dispatch.py _dispatch_profile_allowlist);
- cron: every job in the agent's own profile is paused with AGOS's reason
  (CRON_REASON, Hermes's cron.jobs.pause_job), resumed at check-in with
  `hermes cron resume` — Hermes keeps a slot that passed while paused due, so its
  catch-up policy runs it once (or logs the skip) at check-in (cron/jobs.py
  resume_job): heartbeats, automations, the daily plan are deferred, never run off-hours;
- check-out: an idle agent is off at once. One in the middle of a card finishes it
  and takes no new one: a card comment from AGOS reaches the running worker mid-run
  (Hermes's live comment injection, tools/kanban_tools.py
  inject_new_comments_from_env), asking for its where-I-stopped note on the card.
  At check-out + 2 h its card is parked: `kanban reclaim` (Hermes ends the worker),
  then `kanban schedule` (Hermes's resumable hold, "waiting on time");
- check-in: the jobs resume, each parked card gets a check-in comment and goes back
  with `kanban unblock`; Hermes's dispatcher starts it in a new run whose context
  carries the card's comments and prior attempts (kanban_db.build_worker_context), so
  the agent reads its note and goes on, never from zero, never twice. An agent with a
  heartbeat is woken through it: Hermes's Run now with a one-time check-in prompt
  (`POST /api/jobs/{id}/run` {"prompt"}, cron.jobs.trigger_job manual_run_prompt);
- messages: what the owner writes to an off agent (AGOS chat, its Telegram DM or
  topic) waits in AGOS's queue to Hermes (hermes_inbox, actions/hermes_channel.py
  take_inbox), shown in the chat as his pending message under an "Off until 09:00"
  line; at check-in Hermes gets it and answers it.

The notes are the agents' own, on their cards (marked NOTE_MARK); AGOS's own check-out
/ check-in comments are by AUTHOR. Both are left out of the card page the owner sees.
AGOS keeps the owner's choice (`work_hours.<ws>`) and what its loop last applied per
agent (`work_shift.<ws>`: on / closing / off, since when); every state of record is
Hermes's (the dispatch list, the jobs' paused reason, the cards' status).
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import sqlite3
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.db.app_settings import get_setting, set_setting
from agos_core.engine.cron import WORK_HOURS_REASON as CRON_REASON
from agos_core.engine.cron import CronError
from agos_core.engine.hermes import EngineError
from agos_core.hermes_gateway import cli as hermes_cli
from agos_core.hermes_gateway import hermes_db

log = logging.getLogger("agos.work_hours")

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_WORDS = {
    "mon": "Mon",
    "tue": "Tue",
    "wed": "Wed",
    "thu": "Thu",
    "fri": "Fri",
    "sat": "Sat",
    "sun": "Sun",
}
SETTING = "work_hours.{}"
SHIFT = "work_shift.{}"
COFOUNDER = ""  # the workspace's root profile
GRACE = timedelta(hours=2)
EVERY_SECONDS = 60
AUTHOR = "work-hours"  # AGOS's own comments on cards (hidden from the card page)
NOTE_MARK = "[where I stopped]"
PARK_REASON = "Parked at check-out (work hours): goes on at the next check-in."
CLOSING_NOTE = (
    "Check-out ({at}): your work hours are over. Finish this card in this run and take "
    "no new one. Before this run ends — and at the latest by {limit}, when this card is "
    "parked until the next check-in — add a short comment to this card that starts with "
    f"“{NOTE_MARK}”: what is done, what is left, the next step. Your next run starts "
    "from it."
)
CHECKIN_NOTE = (
    "Check-in ({at}): your work hours started. Read your last comment that starts with "
    f"“{NOTE_MARK}” and go on from there: don't redo what is done."
)
CHECKIN_PROMPT = (
    "Check-in: your work hours start now (you were off since {since}). First read the "
    f"where-I-stopped notes you left on your open cards (comments that start with "
    f"“{NOTE_MARK}”) and go on from them. A parked card goes back on the board by "
    "itself and its own run starts from its note: never redo a card's work here and "
    "never start one twice. Then answer what waited for you while you were off."
)
TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
STATES = ("on", "closing", "off")  # what the loop applied to Hermes
Shift = Literal["on", "off", "staying", "finishing"]  # what the pages show
OPEN = ("triage", "todo", "ready", "running", "blocked", "scheduled", "review")

_last_check: float | None = None
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


# ---- the owner's week ------------------------------------------------------------------


def _minutes(text: Any, day: str, which: str) -> int:
    found = TIME.match(str(text or "").strip())
    if found is None:
        raise ActionError(f"{DAY_WORDS[day]}: {which} is a time like 09:00.")
    return int(found[1]) * 60 + int(found[2])


def default_days() -> dict[str, dict[str, str] | None]:
    return {
        d: ({"from": "09:00", "to": "18:00"} if d not in ("sat", "sun") else None) for d in DAYS
    }


def clean(data: Any) -> dict[str, Any]:
    """The owner's work hours, checked: `on` and a range or None (OFF) per day.
    An overnight range (`to` before `from`) ends the next morning."""
    if not isinstance(data, dict):
        raise ActionError("Work hours are a week of days.")
    days_in = data.get("days")
    days: dict[str, dict[str, str] | None] = {}
    given = days_in if isinstance(days_in, dict) else default_days()
    for day in DAYS:
        span = given.get(day)
        if span is None or span is False or (isinstance(span, dict) and span.get("off")):
            days[day] = None
            continue
        if not isinstance(span, dict):
            raise ActionError(f"{DAY_WORDS[day]}: give a from and a to time, or OFF.")
        start = _minutes(span.get("from"), day, "from")
        end = _minutes(span.get("to"), day, "to")
        if start == end:
            raise ActionError(f"{DAY_WORDS[day]}: from and to are the same time.")
        days[day] = {
            "from": f"{start // 60:02d}:{start % 60:02d}",
            "to": f"{end // 60:02d}:{end % 60:02d}",
        }
    return {"on": bool(data.get("on")), "days": days}


def _stored(core: Core, workspace_id: str) -> dict[str, Any]:
    found = get_setting(core.db, SETTING.format(workspace_id), None)
    return found if isinstance(found, dict) else {}


def schedule(core: Core, workspace_id: str) -> dict[str, Any]:
    """The owner's week (OFF = always on, today's behaviour, until he turns it on)."""
    stored = _stored(core, workspace_id)
    try:
        return clean({"on": stored.get("on"), "days": stored.get("days")})
    except ActionError:
        return {"on": False, "days": default_days()}


def zone(core: Core) -> ZoneInfo:
    """The owner's clock (General → timezone, Hermes's own setting); UTC when unset."""
    from agos_core.actions.owner_time import owner_zone, zone_of

    try:
        name = owner_zone(core)
    except (OSError, ValueError):
        name = ""
    return zone_of(name) or ZoneInfo("UTC")


def shifts(
    days: dict[str, Any], tz: ZoneInfo, at: datetime, back: int = 2, ahead: int = 8
) -> list[tuple[datetime, datetime]]:
    """Every work shift (start, end; UTC) from `back` days before `at` to `ahead` days
    after, in the owner's zone (its daylight saving included), touching ones merged."""
    local = at.astimezone(tz).date()
    out: list[tuple[datetime, datetime]] = []
    for n in range(-back, ahead + 1):
        day = local + timedelta(days=n)
        span = days.get(DAYS[day.weekday()])
        if not span:
            continue
        sh, sm = (int(x) for x in str(span["from"]).split(":"))
        eh, em = (int(x) for x in str(span["to"]).split(":"))
        start = datetime(day.year, day.month, day.day, sh, sm, tzinfo=tz)
        end_day = day + timedelta(days=1) if (eh, em) <= (sh, sm) else day
        end = datetime(end_day.year, end_day.month, end_day.day, eh, em, tzinfo=tz)
        out.append((start.astimezone(UTC), end.astimezone(UTC)))
    out.sort()
    merged: list[tuple[datetime, datetime]] = []
    for start, end in out:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def open_shift(
    days: dict[str, Any], tz: ZoneInfo, at: datetime
) -> tuple[datetime, datetime] | None:
    return next((s for s in shifts(days, tz, at) if s[0] <= at < s[1]), None)


def next_check_in(days: dict[str, Any], tz: ZoneInfo, at: datetime) -> datetime | None:
    """The next shift's start after `at` (inside a shift: the one after it)."""
    return next((s for s, _ in shifts(days, tz, at) if s > at), None)


def last_check_out(days: dict[str, Any], tz: ZoneInfo, at: datetime) -> datetime | None:
    return max((e for _, e in shifts(days, tz, at) if e <= at), default=None)


def _iso(at: datetime | None) -> str | None:
    return at.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z") if at else None


def _parse(text: Any) -> datetime | None:
    try:
        found = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return found if found.tzinfo else found.replace(tzinfo=UTC)


def clock() -> datetime:
    return datetime.now(UTC)


def _now(at: datetime | None) -> datetime:
    return at if at is not None else clock()


def stay_agents(stored: dict[str, Any], at: datetime) -> list[str]:
    """Who stays on today: the pick until its end (the next check-in), then nobody."""
    found = stored.get("stay")
    stay: dict[str, Any] = found if isinstance(found, dict) else {}
    until = _parse(stay.get("until")) if stay else None
    if until is None or at >= until:
        return []
    return [str(a) for a in stay.get("agents") or [] if isinstance(a, str)]


def enabled(core: Core, workspace_id: str) -> bool:
    """Work hours are on for this workspace (one settings read: cheap anywhere)."""
    return bool(_stored(core, workspace_id).get("on"))


def wanted_on(core: Core, workspace_id: str, agent: str, at: datetime | None = None) -> bool:
    """Whether this agent works now (\"\" = the Co-Founder)."""
    when = _now(at)
    stored = _stored(core, workspace_id)
    if not stored.get("on"):
        return True
    if agent in stay_agents(stored, when):
        return True
    return open_shift(schedule(core, workspace_id)["days"], zone(core), when) is not None


def off_now(core: Core, workspace_id: str, at: datetime | None = None) -> set[str]:
    """The agents that are off now (\"\" = the Co-Founder); empty when work hours are off."""
    from agos_core.actions import agent_profiles

    if not _stored(core, workspace_id).get("on"):
        return set()
    names = [COFOUNDER, *agent_profiles.team_names(core, workspace_id)]
    return {n for n in names if not wanted_on(core, workspace_id, n, at)}


def holds(core: Core, workspace_id: str, agent: str | None, at: datetime | None = None) -> bool:
    """A message to this agent waits for its check-in (AGOS chat, Telegram)."""
    return not wanted_on(core, workspace_id, agent or COFOUNDER, at)


# ---- the owner's choices -------------------------------------------------------------


def _agent_name(core: Core, workspace_id: str, agent: Any) -> str:
    from agos_core.actions import agent_profiles

    name = str(agent or "").strip().lstrip("@")
    if name in ("", "cofounder", "co-founder", "Co-Founder"):
        return COFOUNDER
    if name not in agent_profiles.team_names(core, workspace_id):
        raise ActionError(f"@{name} isn't on this workspace's team.")
    return name


def save(core: Core, workspace_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Settings → Work hours (the owner's or the Co-Founder's set_work_hours)."""
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    week = clean(data)
    stored = _stored(core, workspace_id)
    set_setting(core.db, SETTING.format(workspace_id), {**stored, **week})
    apply_soon(core, workspace_id)
    return view(core, workspace_id)


def set_stay(
    core: Core, workspace_id: str, agents: list[Any], at: datetime | None = None
) -> dict[str, Any]:
    """Who stays on today: these agents keep working until the next check-in (an empty
    list = nobody)."""
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    when = _now(at)
    names = sorted({_agent_name(core, workspace_id, a) for a in agents})
    stored = _stored(core, workspace_id)
    until = next_check_in(schedule(core, workspace_id)["days"], zone(core), when)
    if until is None:
        until = when + timedelta(days=1)  # no work day ahead: today only
    stay = {"agents": names, "until": _iso(until)} if names else {}
    set_setting(core.db, SETTING.format(workspace_id), {**stored, "stay": stay})
    apply_soon(core, workspace_id)
    return view(core, workspace_id, at)


def wake(core: Core, workspace_id: str, agent: Any, at: datetime | None = None) -> dict[str, Any]:
    """Wake now: the agent is on for today (the same as picking it to stay on)."""
    when = _now(at)
    name = _agent_name(core, workspace_id, agent)
    current = stay_agents(_stored(core, workspace_id), when)
    return set_stay(core, workspace_id, [*current, name], when)


# ---- what the pages show ---------------------------------------------------------------


def _local_words(at: datetime | None, tz: ZoneInfo, now: datetime) -> str:
    """'09:00' today, 'Tue 09:00' another day (the owner's clock)."""
    if at is None:
        return ""
    local = at.astimezone(tz)
    if local.date() == now.astimezone(tz).date():
        return local.strftime("%H:%M")
    return f"{DAY_WORDS[DAYS[local.weekday()]]} {local.strftime('%H:%M')}"


def agent_state(
    core: Core, workspace_id: str, agent: str, at: datetime | None = None
) -> Shift | None:
    """'on' / 'off' / 'staying' / 'finishing' (None: work hours are off)."""
    when = _now(at)
    stored = _stored(core, workspace_id)
    if not stored.get("on"):
        return None
    if agent in stay_agents(stored, when):
        return "staying"
    applied = _shift(core, workspace_id).get(agent, {})
    if wanted_on(core, workspace_id, agent, when):
        return "on"
    return "finishing" if applied.get("state") == "closing" else "off"


def view(core: Core, workspace_id: str, at: datetime | None = None) -> dict[str, Any]:
    """Settings → Work hours, the status chips and the chats' off line, in one read."""
    from agos_core.actions import agent_profiles
    from agos_core.actions.owner_time import owner_zone

    when = _now(at)
    week = schedule(core, workspace_id)
    stored = _stored(core, workspace_id)
    tz = zone(core)
    stay = stay_agents(stored, when)
    upcoming = next_check_in(week["days"], tz, when)
    current = open_shift(week["days"], tz, when) if week["on"] else None
    stay_until = (stored.get("stay") or {}).get("until") if stay else None
    agents = []
    for name in [COFOUNDER, *agent_profiles.team_names(core, workspace_id)]:
        state = agent_state(core, workspace_id, name, when)
        agents.append(
            {
                "agent": name,
                "state": state,
                # When an off agent is on again (its check-in).
                "until": _iso(upcoming) if state in ("off", "finishing") else None,
                "untilText": _local_words(upcoming, tz, when)
                if state in ("off", "finishing")
                else "",
            }
        )
    try:
        zone_name = owner_zone(core) or "UTC"
    except (OSError, ValueError):
        zone_name = "UTC"
    return {
        "on": week["on"],
        "days": week["days"],
        "zone": zone_name,
        "stay": stay,
        "stayUntil": stay_until,
        "nextCheckIn": _iso(upcoming) if week["on"] else None,
        "nextCheckInText": _local_words(upcoming, tz, when) if week["on"] else "",
        "checkOut": _iso(current[1]) if current else None,
        "checkOutText": _local_words(current[1], tz, when) if current else "",
        "agents": agents,
    }


def chat_agent(core: Core, chat_id: int) -> str | None:
    """Whose answers a chat is: \"\" the Co-Founder, a member's name; None = a group."""
    row = core.db.execute("SELECT kind, agent FROM chats WHERE id = ?", (chat_id,)).fetchone()
    if row is None or row["kind"] == "group":
        return None
    return str(row["agent"] or "")


def off_line(core: Core, workspace_id: str, chat_id: int) -> dict[str, Any] | None:
    """The chat's line while its agent is off: until when, and who (for Wake now)."""
    agent = chat_agent(core, chat_id)
    if agent is None or not _stored(core, workspace_id).get("on"):
        return None
    if not holds(core, workspace_id, agent):
        return None
    when = _now(None)
    tz = zone(core)
    upcoming = next_check_in(schedule(core, workspace_id)["days"], tz, when)
    return {"agent": agent, "until": _iso(upcoming), "untilText": _local_words(upcoming, tz, when)}


def hidden_comment(comment: dict[str, Any]) -> bool:
    """A card comment kept out of the card page: AGOS's check-out / check-in words and
    the agent's where-I-stopped note (Hermes's worker still reads both)."""
    body = str(comment.get("body") or "").lstrip()
    return str(comment.get("author") or "") == AUTHOR or body.startswith(NOTE_MARK)


def off_words(line: dict[str, Any]) -> str:
    """The owner's line while the agent is off (chat, Telegram)."""
    until = str(line.get("untilText") or "")
    head = f"Off until {until}" if until else "Off until the next check-in"
    return f"{head} — your message will be answered at check-in."


# ---- Hermes's switches, per agent -------------------------------------------------------


def _shift(core: Core, workspace_id: str) -> dict[str, dict[str, Any]]:
    found = get_setting(core.db, SHIFT.format(workspace_id), None)
    agents = found.get("agents") if isinstance(found, dict) else None
    return {str(k): dict(v) for k, v in (agents or {}).items() if isinstance(v, dict)}


def _profile(core: Core, workspace_id: str, agent: str) -> str:
    """The agent's Kanban assignee (\"default\" = the Co-Founder, \"a-<name>\" a member)."""
    from agos_core.actions import agent_profiles

    assert core.engine is not None
    if agent == COFOUNDER:
        return core.engine.hermes_name(workspace_id)
    return core.engine.hermes_name(agent_profiles.key(workspace_id, agent))


def cards(core: Core, workspace_id: str) -> list[dict[str, Any]]:
    """The open cards on Hermes's board (read only): id, status, assignee, and whether
    AGOS's check-out parked it (its last `scheduled` event has PARK_REASON)."""
    from agos_core.actions import agent_profiles

    if core.engine is None:
        return []
    board = agent_profiles.board_db(core, workspace_id)
    if not board.is_file():
        return []
    try:
        with contextlib.closing(hermes_db.connect_ro(board, timeout=2)) as db:
            rows = db.execute(
                """SELECT t.id, t.status, t.assignee,
                          (SELECT e.payload FROM task_events e WHERE e.task_id = t.id
                             AND e.kind = 'scheduled' ORDER BY e.id DESC LIMIT 1)
                     FROM tasks t WHERE t.status NOT IN ('done', 'archived')"""
            ).fetchall()
    except sqlite3.Error as error:
        log.warning("board of %s not read for work hours: %s", workspace_id, error)
        return []
    out = []
    for card_id, status, assignee, payload in rows:
        reason = ""
        with contextlib.suppress(ValueError, TypeError, AttributeError):
            reason = str((json.loads(payload or "{}") or {}).get("reason") or "")
        out.append(
            {
                "id": str(card_id),
                "status": str(status or ""),
                "assignee": str(assignee or ""),
                "parked": str(status) == "scheduled" and reason == PARK_REASON,
            }
        )
    return out


def kanban(core: Core, workspace_id: str, *args: str) -> bool:
    """One Hermes Kanban CLI call in the workspace's root; False when Hermes refused."""
    if core.engine is None:
        return False
    try:
        hermes_cli.cli(core.engine, workspace_id, "kanban", *args)
    except (EngineError, OSError) as error:
        log.warning("work hours: kanban %s on %s: %s", args[0], workspace_id, error)
        return False
    return True


def _jobs(core: Core, workspace_id: str, agent: str) -> tuple[Any, Any, list[dict[str, Any]]]:
    """(bridge, the agent's profile home, its Hermes cron jobs); bridge None = no cron."""
    from agos_core.actions import automations as automation_actions
    from agos_core.engine.cron import read_jobs

    bridge = automation_actions.cron_bridge(core)
    if bridge is None or core.engine is None:
        return None, None, []
    home = automation_actions.homes(core, workspace_id).get(agent)
    if home is None or not (home / "config.yaml").is_file():
        return None, None, []
    custom = getattr(core.engine, "cron_bridge", None)
    try:
        jobs = custom.job_states(home) if custom is not None else read_jobs(home)
    except (CronError, OSError, ValueError) as error:
        log.warning("cron of %s in %s not read: %s", agent or "Co-Founder", workspace_id, error)
        return None, None, []
    return bridge, home, list(jobs)


def hold_cron(core: Core, workspace_id: str, agent: str) -> int:
    """Every running job of the agent's own cron paused with CRON_REASON (Hermes's
    pause with a reason). Cheap when nothing is on: one read of its jobs.json."""
    bridge, home, jobs = _jobs(core, workspace_id, agent)
    held = 0
    for job in jobs:
        if not job.get("enabled"):
            continue
        try:
            bridge.pause(home, str(job["id"]), CRON_REASON)
            held += 1
        except (CronError, EngineError, OSError) as error:
            log.warning("job %s not paused off-hours: %s", job.get("id"), error)
    return held


def release_cron(core: Core, workspace_id: str, agent: str, prompt: str) -> int:
    """The jobs the off-hours held, back on (`hermes cron resume`: a slot that passed is
    still due, so Hermes runs it once). Its heartbeat is woken with the check-in prompt
    instead (Hermes's Run now with a one-time prompt, which also resumes it)."""
    from agos_core.actions.heartbeat import JOB_NAME

    bridge, home, jobs = _jobs(core, workspace_id, agent)
    released = 0
    for job in jobs:
        if job.get("enabled") or job.get("paused_reason") != CRON_REASON:
            continue
        try:
            if job.get("name") == JOB_NAME:
                try:
                    bridge.run_now(home, str(job["id"]), prompt=prompt)
                except (CronError, EngineError, OSError):
                    bridge.resume(home, str(job["id"]))  # its gateway is down: on time
            else:
                bridge.resume(home, str(job["id"]))
            released += 1
        except (CronError, EngineError, OSError) as error:
            log.warning("job %s not resumed at check-in: %s", job.get("id"), error)
    return released


def _check_out(
    core: Core, workspace_id: str, agent: str, at: datetime, week: dict[str, Any], tz: ZoneInfo
) -> dict[str, Any]:
    profile = _profile(core, workspace_id, agent)
    hold_cron(core, workspace_id, agent)
    # Since the shift's end (the core may have been down at check-out itself).
    since = last_check_out(week["days"], tz, at) if week["on"] else None
    since = since if since is not None and since <= at else at
    running = [
        c
        for c in cards(core, workspace_id)
        if c["assignee"] == profile and c["status"] == "running"
    ]
    words = _local_words(since, tz, at)
    limit = _local_words(since + GRACE, tz, at)
    for card in running:
        kanban(
            core,
            workspace_id,
            "comment",
            card["id"],
            CLOSING_NOTE.format(at=words, limit=limit),
            "--author",
            AUTHOR,
        )
    state = "closing" if running else "off"
    return {"state": state, "since": _iso(since), "cards": [c["id"] for c in running]}


def _closing(
    core: Core, workspace_id: str, agent: str, applied: dict[str, Any], at: datetime
) -> dict[str, Any]:
    profile = _profile(core, workspace_id, agent)
    running = [
        c
        for c in cards(core, workspace_id)
        if c["assignee"] == profile and c["status"] == "running"
    ]
    since = _parse(applied.get("since")) or at
    if not running:
        return {**applied, "state": "off"}
    if at < since + GRACE:
        return applied
    parked = []
    for card in running:
        # Hermes ends the worker (reclaim), then holds the card until check-in.
        kanban(core, workspace_id, "reclaim", card["id"], "--reason", PARK_REASON)
        if kanban(core, workspace_id, "schedule", card["id"], PARK_REASON):
            parked.append(card["id"])
    return {**applied, "state": "off", "parked": parked}


def _check_in(
    core: Core, workspace_id: str, agent: str, applied: dict[str, Any], at: datetime, tz: ZoneInfo
) -> None:
    from agos_core.engine import doorbell

    profile = _profile(core, workspace_id, agent)
    since = _parse(applied.get("since"))
    words = _local_words(at, tz, at)
    release_cron(
        core,
        workspace_id,
        agent,
        CHECKIN_PROMPT.format(since=_local_words(since, tz, at) or "before"),
    )
    for card in cards(core, workspace_id):
        if card["assignee"] != profile or not card["parked"]:
            continue
        kanban(
            core,
            workspace_id,
            "comment",
            card["id"],
            CHECKIN_NOTE.format(at=words),
            "--author",
            AUTHOR,
        )
        kanban(core, workspace_id, "unblock", card["id"])
    doorbell.ring(doorbell.INBOX, workspace_id)  # what waited for it goes to Hermes


def _lock(workspace_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(workspace_id, threading.Lock())


def apply(core: Core, workspace_id: str, at: datetime | None = None) -> dict[str, str]:
    """One pass for the workspace: each agent's check-in / check-out on Hermes's own
    switches, as its hours say now. Returns {agent: state applied}. Never raises."""
    from agos_core.actions import agent_profiles, hire_kit

    when = _now(at)
    if core.engine is None:
        return {}
    stored = _stored(core, workspace_id)
    applied = _shift(core, workspace_id)
    if not stored.get("on") and all(v.get("state", "on") == "on" for v in applied.values()):
        return {}
    with _lock(workspace_id):
        week = schedule(core, workspace_id)
        tz = zone(core)
        agents = [COFOUNDER, *agent_profiles.team_names(core, workspace_id)]
        moved = False
        after: dict[str, dict[str, Any]] = {}
        for agent in agents:
            before = applied.get(agent, {"state": "on"})
            now_state = before
            try:
                if wanted_on(core, workspace_id, agent, when):
                    if before.get("state", "on") != "on":
                        _check_in(core, workspace_id, agent, before, when, tz)
                        now_state = {"state": "on"}
                elif before.get("state", "on") == "on":
                    now_state = _check_out(core, workspace_id, agent, when, week, tz)
                else:
                    if before.get("state") == "closing":
                        now_state = _closing(core, workspace_id, agent, before, when)
                    hold_cron(core, workspace_id, agent)  # one turned on meanwhile stays held
            except (CronError, EngineError, OSError, ActionError) as error:
                log.warning(
                    "work hours of %s in %s: %s", agent or "Co-Founder", workspace_id, error
                )
            if now_state.get("state") != before.get("state", "on"):
                moved = True
            after[agent] = now_state
        set_setting(
            core.db,
            SHIFT.format(workspace_id),
            {"agents": {k: v for k, v in after.items() if v.get("state") != "on"}},
        )
        if moved:
            hire_kit.sync_dispatch(core, workspace_id)
    return {k: str(v.get("state")) for k, v in after.items()}


def _run_later(fn: Callable[[], Any]) -> None:
    threading.Thread(target=fn, daemon=True, name="agos-work-hours").start()


def apply_soon(core: Core, workspace_id: str) -> None:
    """The owner's change reaches Hermes now, off the request (a pass takes seconds)."""

    def run() -> None:
        try:
            apply(core, workspace_id)
        except Exception:
            log.exception("work hours of %s not applied", workspace_id)

    _run_later(run)


def keep(core: Core, now: float | None = None) -> list[str]:
    """The automation loop's pass, at most once a minute: every workspace whose work
    hours are on (or still hold an agent)."""
    global _last_check
    at = time.monotonic() if now is None else now
    if _last_check is not None and at - _last_check < EVERY_SECONDS:
        return []
    _last_check = at
    done = []
    rows = core.db.execute(
        "SELECT key FROM app_settings WHERE key LIKE ? OR key LIKE ?",
        (SETTING.format("%"), SHIFT.format("%")),
    ).fetchall()
    seen = set()
    for row in rows:
        workspace_id = str(row["key"]).split(".", 1)[1]
        if workspace_id in seen:
            continue
        seen.add(workspace_id)
        exists = core.db.execute(
            "SELECT 1 FROM workspaces WHERE id = ? AND archived_at IS NULL AND deleted_at IS NULL",
            (workspace_id,),
        ).fetchone()
        if exists is None:
            continue
        try:
            apply(core, workspace_id)
            done.append(workspace_id)
        except Exception:
            log.exception("work hours of %s not kept", workspace_id)
    return done
