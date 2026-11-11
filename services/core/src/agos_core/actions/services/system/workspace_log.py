"""The workspace Log: one timeline of everything that happened in a project.

Moved out of api/log.py (the router keeps only the HTTP mapping).

What each agent and the Co-Founder did, every automation run, webhook, message
sent to a channel, and every problem: a failed run or answer, an error of AGOS
itself. Each line says where (the automation, chat, channel...) and, for a
problem, the cause, with a link there.

Each line also says WHO did it (step 55, Paperclip F35's attribution): the owner
("You"), the Co-Founder, a team member, an automation, or AGOS / Hermes itself; the
page filters by who, by area and by date.

Read-only. What the agents did is read from Hermes: its Kanban events, its cron
runs, its webhook route script's notes, the turns its agent.log says ended badly
(each mapped to its chat through Hermes's sessions), its errors.log and its
gateway state. AGOS adds only what is its own: the owner's audit trail
(`activity`), the Co-Founder's actions and capability requests, the cards and relayed
replies it sends (`channel_outbox`) and its own errors (`system_log`). Secrets
never reach it (texts go through `redact`).

Must not: write anything, or open a Hermes store itself (hermes_gateway/store_rows.py
reads them; db/log_rows.py holds AGOS's own queries).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from agos_core.actions.system_log import redact
from agos_core.actions.workspaces import require_workspace
from agos_core.db import status_reads as log_rows
from agos_core.db.chats import chat_title
from agos_core.hermes_gateway import store_rows

__all__ = ["ActorKind", "Area", "Level", "LogActor", "LogEntry", "LogPage", "page"]


Level = Literal["info", "ok", "warn", "error"]
Area = Literal[
    "task", "automation", "webhook", "chat", "cofounder", "goal", "status", "channel", "system"
]
ActorKind = Literal["owner", "cofounder", "member", "automation", "system"]

PER_SOURCE = 400

# The owner's audit trail (activity): its kinds' levels; the rest are "info". The
# board's own events are Hermes's Kanban (actions/kanban_board.EVENTS).
_ACTIVITY_LEVEL: dict[str, Level] = {
    "automation.skipped": "warn",
}


class LogEntry(BaseModel):
    id: str
    at: str
    level: Level
    area: Area
    where: str = Field(description="Where it happened: the task, automation, chat...")
    text: str
    cause: str = Field(default="", description="For a problem: why it happened.")
    href: str | None = None
    # Who did it: its kind, its name as shown, and the key the actor filter takes
    # (owner, cofounder, member:<name>, automation:<id>, system).
    actor_kind: ActorKind = "system"
    actor: str = "AGOS"
    actor_key: str = "system"


class LogActor(BaseModel):
    key: str
    label: str
    kind: ActorKind


class LogPage(BaseModel):
    entries: list[LogEntry]
    problems_24h: int
    more: bool
    # Everyone who did something in the entries read (the page's actor filter).
    actors: list[LogActor] = Field(default_factory=list)


OWNER = ("owner", "You", "owner")
COFOUNDER = ("cofounder", "Co-Founder", "cofounder")
SYSTEM = ("system", "AGOS", "system")
HERMES = ("system", "Engine", "system")

# The owner's audit trail is mostly his own clicks; these kinds are AGOS's or
# Hermes's own doing, an automation's, or the Co-Founder's.
_ACTIVITY_SYSTEM = {
    "engine.blocked",
    "usage.paused",
    "task.tokens",
    "agent.power",
    "room.refused",
    "watchdog.act",
    "playbooks.one_copy",
}
_ACTIVITY_AUTOMATION = {
    "automation.skipped",
    "automation.hook",
    "automation.catch_up",  # a run missed while the server was off (actions/catch_up.py)
    "automation.catch_up_skipped",
}
_ACTIVITY_COFOUNDER = {"status.written"}
_BY = re.compile(r" by ([^()]+?)(?: \(|$)")


def _member(name: str) -> tuple[str, str, str]:
    return ("member", f"@{name}", f"member:{name}")


def _named(who: str, team: set[str]) -> tuple[str, str, str]:
    """An author's words (Owner, You, Co-Founder, a member's name) as an actor."""
    w = who.strip()
    if w.lower() in ("owner", "you", "the owner", "user"):
        return OWNER
    if w.lower() in ("co-founder", "cofounder", "the co-founder"):
        return COFOUNDER
    if w.lstrip("@") in team:
        return _member(w.lstrip("@"))
    return SYSTEM


def _activity_actor(kind: str, text: str, team: set[str]) -> tuple[str, str, str]:
    if kind in _ACTIVITY_SYSTEM:
        return SYSTEM
    if kind in _ACTIVITY_AUTOMATION:
        return ("automation", "Automation", "automation")
    if kind in _ACTIVITY_COFOUNDER:
        return COFOUNDER
    if kind == "docs.changed":
        found = _BY.search(text)
        return _named(found.group(1), team) if found else OWNER
    return OWNER


def _team(core: Any, ws: str) -> set[str]:
    if core.engine is None:
        return set()
    from agos_core.actions import agent_profiles

    return set(agent_profiles.team_names(core, ws))


def _as(entry: LogEntry, actor: tuple[str, str, str]) -> LogEntry:
    kind, label, key = actor
    return entry.model_copy(update={"actor_kind": kind, "actor": label, "actor_key": key})


def _clip(text: Any, n: int = 1200) -> str:
    t = redact(" ".join(str(text or "").split()))
    return t if len(t) <= n else t[: n - 1] + "…"


def _entries(core: Any, ws: str, before: str) -> list[LogEntry]:
    """Every source's lines before `before` (a page's worth each), unsorted."""
    out = _activity(core, ws, before)
    out += _automation_runs(core, ws, before)
    # 2c. The Kanban (Hermes's board): what happened to each card.
    out += _kanban(core, ws, before)
    # 2d. Hermes's cron runs, read live: AGOS's one-agent automations and the
    # agents' own scheduled jobs.
    out += _cron(core, ws, before)
    # 3. Webhooks received: what Hermes's route script noted of each delivery.
    out += _webhooks(core, ws, before)
    # 4. Chats: answers that failed (Hermes's agent.log, mapped through its sessions).
    out += _failed_turns(core, ws, before)
    out += _cofounder(core, ws, before)
    out += _channels(core, ws, before)
    out += _system(core, ws, before)
    # 11. Hermes's own errors in this workspace (its profile's errors.log).
    out += _hermes_errors(core, ws, before)
    return out


def _activity(core: Any, ws: str, before: str) -> list[LogEntry]:
    """The owner's audit trail, each line put down to who did it."""
    out: list[LogEntry] = []
    args = (ws, before, PER_SOURCE)
    team = _team(core, ws)
    # 1. Everything the board and the team did (activity).
    for r in log_rows.activity(core.db, *args):
        kind = str(r["kind"])
        area: Area = (
            "automation"
            if kind.startswith("automation.")
            else "channel"
            if kind.startswith("channel")
            else "task"
            if kind.startswith(("task.", "docs."))
            else "goal"
            if kind.startswith("goal.")
            else "status"
            if kind.startswith("status.")
            else "system"
        )
        out.append(
            _as(
                LogEntry(
                    id=f"activity:{r['id']}",
                    at=r["created_at"],
                    level=_ACTIVITY_LEVEL.get(kind, "info"),
                    area=area,
                    where=kind,
                    text=_clip(r["text"]),
                    href=f"/w/{ws}/vision"
                    if area == "goal"
                    else f"/w/{ws}/status"
                    if area == "status"
                    else None,
                ),
                _activity_actor(kind, str(r["text"]), team),
            )
        )
    return out


def _automation_runs(core: Any, ws: str, before: str) -> list[LogEntry]:
    """Automation runs on the Kanban, read from Hermes."""
    out: list[LogEntry] = []
    autos = f"/w/{ws}/automations"
    # 2b. Runs on the Kanban (team steps, check first, webhooks), read from Hermes.
    from agos_core.actions import automation_cards

    for automation, run in automation_cards.of_workspace(core, ws):
        at = run.finished_at
        if at is None or at >= before:
            continue
        out.append(
            _as(
                LogEntry(
                    id=f"automation-run:{automation.id}:{run.id}",
                    at=at,
                    level="error" if run.stopped else "ok",
                    area="automation",
                    where=f"Automation “{automation.name}”",
                    text=f"Run {'stopped' if run.stopped else 'finished'} ({run.source})",
                    cause=_clip(run.report) if run.stopped else "",
                    href=f"{autos}?runs={automation.id}",
                ),
                ("automation", automation.name or "Automation", f"automation:{automation.id}"),
            )
        )
    return out


def _cofounder(core: Any, ws: str, before: str) -> list[LogEntry]:
    """The Co-Founder's actions and capability requests."""
    out: list[LogEntry] = []
    args = (ws, before, PER_SOURCE)
    # 5. What the Co-Founder did from the chat (agents, skills, automations...).
    for r in log_rows.cofounder_actions(core.db, *args):
        status = str(r["status"])
        lvl: Level = {"done": "ok", "failed": "error", "rejected": "info", "undone": "info"}.get(
            status, "warn"
        )  # type: ignore[assignment]
        out.append(
            _as(
                LogEntry(
                    id=f"cofounder:{r['id']}",
                    at=r["at"],
                    level=lvl,
                    area="cofounder",
                    where="Co-Founder",
                    text={
                        "done": f"Done: {r['title']}",
                        "failed": f"Couldn't do: {r['title']}",
                        "rejected": f"Refused by you: {r['title']}",
                        "undone": f"Undone: {r['title']}",
                        "proposed": f"Asks you: {r['title']}",
                    }.get(status, f"{status}: {r['title']}"),
                    cause=_clip(r["error"]) if status == "failed" else "",
                    href=f"/w/{ws}/messages?c={r['chat_id']}" if r["chat_id"] else None,
                ),
                OWNER if status in ("rejected", "undone") else COFOUNDER,
            )
        )
    for r in log_rows.capability_results(core.db, *args):
        failed = r["status"] == "failed"
        out.append(
            _as(
                LogEntry(
                    id=f"capability:{r['id']}",
                    at=r["created_at"],
                    level="error" if failed else "ok",
                    area="cofounder",
                    where=f"{r['kind']} “{r['title']}”",
                    text=("Couldn't connect: " if failed else "Connected: ") + str(r["title"]),
                    cause=_clip(r["error"]) if failed else "",
                ),
                COFOUNDER,
            )
        )
    return out


def _channels(core: Any, ws: str, before: str) -> list[LogEntry]:
    """What channels sent, and bots Hermes can't run."""
    out: list[LogEntry] = []
    args = (ws, before, PER_SOURCE)
    # 6. Channels (Telegram, Buzz): what was sent, and sending problems.
    for r in log_rows.outbox(core.db, *args):
        failed = bool(r["error"]) and not r["sent_id"]
        out.append(
            LogEntry(
                id=f"channel:{r['id']}",
                at=r["created_at"],
                level="error" if failed else "info",
                area="channel",
                where=f"{str(r['kind']).capitalize()} “{r['name']}”",
                text=("Couldn't send: " if failed else "Sent: ") + _clip(r["body"], 200),
                cause=f"{_clip(r['error'])} (after {r['attempts']} tries)" if failed else "",
            )
        )
    # A bot Hermes can't run: read live from the gateway's gateway_state.json.
    from agos_core.actions import hermes_channel

    for r in log_rows.bot_connections(core.db, ws):
        status, reason = hermes_channel.channel_state(core, r)
        if status != "error":
            continue
        out.append(
            LogEntry(
                id=f"connection:{r['id']}",
                at=hermes_channel.channel_since(core, r)[1] or r["created_at"],
                level="error",
                area="channel",
                where=f"{str(r['kind']).capitalize()} “{r['name']}”",
                text="The channel is not connected",
                cause=_clip(reason or "unknown"),
                href=f"/w/{ws}/settings",
            )
        )
    return out


def _system(core: Any, ws: str, before: str) -> list[LogEntry]:
    """AGOS's own errors (this workspace, or the whole app)."""
    out: list[LogEntry] = []
    args = (ws, before, PER_SOURCE)
    # 10. AGOS's own errors (this workspace, or the whole app).
    for r in log_rows.system_log(core.db, *args):
        text = str(r["text"])
        main, _, cause = text.partition(" — ")
        out.append(
            LogEntry(
                id=f"system:{r['id']}",
                at=r["created_at"],
                level="error" if r["level"] == "error" else "warn",
                area="system",
                where=f"AGOS · {str(r['source']).removeprefix('agos.') or 'core'}"
                + ("" if r["workspace_id"] else " (whole app)"),
                text=_clip(main),
                cause=_clip(cause),
            )
        )
    return out


def _iso(seconds: Any) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(float(seconds), UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _board_actor(core: Any, ws: str) -> Any:
    """Who a board event is put down to: the profile of the run that made it (a
    member or the Co-Founder), the card's creator or a comment's author (the owner
    when Hermes recorded `owner` / `user`), an automation for its own cards, else the
    board itself (Hermes recorded nobody: a click in AGOS or a CLI call)."""
    from agos_core.actions import kanban_board

    members = kanban_board._members(core, ws)
    cofounder = core.engine.hermes_name(ws) if core.engine is not None else ""
    names = {str(r["id"]): str(r["name"] or "") for r in log_rows.automation_names(core.db, ws)}

    def actor(raw: str, key: str, kind: str = "") -> tuple[str, str, str]:
        if kind == "created" and key.startswith("agos-automation:"):
            number = key.split(":")[1]
            label = names.get(number) or f"Automation {number}"
            return ("automation", label, f"automation:{number}")
        if raw in members:
            name = members[raw]["name"]
            return COFOUNDER if name == kanban_board.COFOUNDER else _member(name)
        if raw and raw == cofounder:
            return COFOUNDER
        if raw in (kanban_board.OWNER, "user"):
            return OWNER
        if raw:
            return _named(raw, {m["name"] for m in members.values()})
        return ("system", "Kanban", "system")

    return actor


def _kanban(core: Any, ws: str, before: str) -> list[LogEntry]:
    from agos_core.actions import kanban_board

    out: list[LogEntry] = []
    events = kanban_board.events(core, ws, PER_SOURCE)
    actor = _board_actor(core, ws) if events else None
    for e in events:
        at = _iso(e["at"])
        if at >= before:
            continue
        word, text = kanban_board.EVENTS[e["kind"]]
        level = cast(Level, word)
        payload = e["payload"]
        detail = str(payload.get("summary") or payload.get("reason") or payload.get("error") or "")
        if e["kind"] == "assigned" and actor is not None:
            to = str(payload.get("assignee") or "")
            detail = f"to {actor(to, '')[1]}" if to else "to nobody"
        entry = LogEntry(
            id=f"kanban:{e['id']}",
            at=at,
            level=level,
            area="task",
            where=f"Card {e['card']} “{e['title']}”",
            text=f"{text}: {_clip(detail, 300)}" if detail and level != "error" else text,
            cause=_clip(detail) if level == "error" else "",
            href=f"/w/{ws}/kanban?card={e['card']}",
        )
        out.append(
            _as(entry, actor(str(e.get("actor") or ""), str(e.get("key") or ""), e["kind"]))
            if actor
            else entry
        )
    return out


def _cron(core: Any, ws: str, before: str) -> list[LogEntry]:
    if core.engine is None:
        return []
    from agos_core.actions.automations import homes

    # Every profile's cron: the Co-Founder's, and each member's (its automations).
    out: list[LogEntry] = []
    for agent, home in homes(core, ws).items():
        owner = _member(agent) if agent else COFOUNDER
        out += [
            e if e.actor_kind == "automation" else _as(e, owner)
            for e in _cron_of(core, ws, home / "cron", before)
        ]
    return out


def _cron_of(core: Any, ws: str, cron: Any, before: str) -> list[LogEntry]:
    import json

    try:
        jobs = json.loads((cron / "jobs.json").read_text()).get("jobs") or []
    except (OSError, ValueError, AttributeError):
        jobs = []
    names = {
        str(j.get("id")): str(j.get("name") or j.get("id")) for j in jobs if isinstance(j, dict)
    }
    # An AGOS automation's runs are read here too (Hermes keeps them).
    # Its name is Hermes's job's own (AGOS's row holds it only until Hermes has it).
    automations = {
        str(r["hermes_job_id"]): (
            int(r["id"]),
            str(r["name"]) or names.get(str(r["hermes_job_id"]), f"Automation {r['id']}"),
        )
        for r in log_rows.automation_jobs(core.db, ws)
    }
    out: list[LogEntry] = []
    for r in store_rows.read(
        Path(cron) / "executions.db",
        """SELECT id, job_id, status, started_at, finished_at, error FROM executions
           WHERE status IN ('completed', 'failed') ORDER BY COALESCE(finished_at, started_at) DESC
           LIMIT ?""",
        (PER_SOURCE,),
    ):
        at = _utc(str(r["finished_at"] or r["started_at"] or ""))
        if not at or at >= before:
            continue
        failed = r["status"] == "failed"
        mine = automations.get(str(r["job_id"]))
        entry = LogEntry(
            id=f"cron:{r['id']}",
            at=at,
            level="error" if failed else "ok",
            area="automation",
            where=(
                f"Automation “{mine[1]}”"
                if mine
                else f"Scheduled job “{names.get(str(r['job_id']), r['job_id'])}”"
            ),
            text="Run failed" if failed else "Run finished",
            cause=_clip(r["error"] or "no reason given") if failed else "",
            href=(
                f"/w/{ws}/automations?runs={mine[0]}" if mine else f"/w/{ws}/automations#scheduled"
            ),
        )
        out.append(_as(entry, ("automation", mine[1], f"automation:{mine[0]}")) if mine else entry)
    return out


def _webhooks(core: Any, ws: str, before: str) -> list[LogEntry]:
    """The deliveries Hermes's webhook route script noted, per automation."""
    from agos_core.actions import hooks

    out: list[LogEntry] = []
    routed = hooks.routes(core, ws)  # Hermes's webhook routes, by automation
    for r in log_rows.automation_names(core.db, ws):
        if int(r["id"]) not in routed:
            continue
        for item in hooks.noted(core, ws, int(r["id"]))[:PER_SOURCE]:
            at = str(item.get("at") or "")
            if not at or at >= before:
                continue
            status = str(item.get("status") or "")
            event = str(item.get("event") or "")
            out.append(
                LogEntry(
                    actor_kind="automation",
                    actor=_name(core, ws, r),
                    actor_key=f"automation:{r['id']}",
                    id=f"webhook:{r['id']}:{item['n']}",
                    at=at,
                    level="error" if status == "rejected" else "info",
                    area="webhook",
                    where=f"Automation “{_name(core, ws, r)}”" + (f" · {event}" if event else ""),
                    text={
                        "rejected": "Webhook refused",
                        "duplicate": "Webhook received twice, ignored",
                    }.get(status, "Webhook received, the run started"),
                    cause=_clip(item.get("detail")) if status == "rejected" else "",
                    href=f"/w/{ws}/automations?runs={r['id']}",
                )
            )
    return out


def _name(core: Any, ws: str, row: Any) -> str:
    """An automation's name: AGOS's row while no Hermes job holds it, else the job's."""
    if row["name"]:
        return str(row["name"])
    from agos_core.actions import automations as automations_actions

    found = automations_actions.get(core, ws, int(row["id"]))
    return found.name if found is not None else f"Automation {row['id']}"


def _tail(path: Any, size: int) -> list[str]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            end = handle.tell()
            handle.seek(max(0, end - size))
            return list(handle.read().decode("utf-8", "replace").splitlines())
    except OSError:
        return []


def _failed_turns(core: Any, ws: str, before: str) -> list[LogEntry]:
    """Turns of the workspace's chats that Hermes ended without an answer: the turn
    records with Hermes's reason (its on_session_end hook, actions/hermes_channel.py
    turn_ended)."""
    rows = log_rows.failed_turns(core.db, ws, before, PER_SOURCE)
    out: list[LogEntry] = []
    for chat in rows:
        kind = str(chat["kind"])
        who = f"@{chat['agent']}" if chat["agent"] else "the Co-Founder"
        out.append(
            LogEntry(
                actor_kind="member" if chat["agent"] else "cofounder",
                actor=who if chat["agent"] else "Co-Founder",
                actor_key=f"member:{chat['agent']}" if chat["agent"] else "cofounder",
                id=f"chat:turn:{chat['turn_id']}",
                at=str(chat["turn_at"]),
                level="error",
                area="chat",
                where=f"Chat “{chat_title(core.db, chat) or 'Chat'}”",
                text=f"The answer of {who} failed",
                cause=_clip(str(chat["turn_error"] or "")),
                href=(
                    f"/w/{ws}/sessions?chat={chat['id']}"
                    if kind == "chat"
                    else f"/w/{ws}/messages?c={chat['id']}"
                ),
            )
        )
    return out


def _utc(text: str) -> str:
    """Hermes's times (ISO with an offset, or its logs' local "Y-m-d H:M:S,ms") as
    AGOS's UTC ISO."""
    from datetime import UTC, datetime

    try:
        when = datetime.fromisoformat(text.replace(",", "."))
    except ValueError:
        return ""
    if when.tzinfo is None:
        when = when.astimezone()  # the server's own time, like Hermes's logs
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


_LOG_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+) (ERROR|CRITICAL) ([\w.\-]+): (.*)$")


def _hermes_errors(core: Any, ws: str, before: str) -> list[LogEntry]:
    if core.engine is None:
        return []
    lines = _tail(core.engine.profile_home(ws) / "logs" / "errors.log", 256_000)
    out: list[LogEntry] = []
    for n, line in enumerate(reversed(lines)):
        m = _LOG_LINE.match(line)
        if not m:
            continue
        at = _utc(m.group(1))
        if not at or at >= before:
            continue
        main, _, cause = m.group(4).partition(": ")
        out.append(
            LogEntry(
                actor="Engine",
                id=f"hermes:{at}:{n}",
                at=at,
                level="error",
                area="system",
                where=f"Engine · {m.group(3)}",
                text=_clip(main if cause else m.group(4)),
                cause=_clip(cause),
            )
        )
        if len(out) >= PER_SOURCE:
            break
    return out


_KIND_ORDER = {"owner": 0, "cofounder": 1, "member": 2, "automation": 3, "system": 4}


def _actors(entries: list[LogEntry]) -> list[LogActor]:
    seen: dict[str, LogActor] = {}
    for e in entries:
        if e.actor_key not in seen:
            label = "AGOS" if e.actor_key == "system" else e.actor
            seen[e.actor_key] = LogActor(key=e.actor_key, label=label, kind=e.actor_kind)
    return sorted(seen.values(), key=lambda a: (_KIND_ORDER[a.kind], a.label.lower()))


def _actor_matches(entry: LogEntry, wanted: str) -> bool:
    """`owner`, `cofounder`, `system`, `member` (any member), `member:<name>`,
    `automation` (any), `automation:<id>`."""
    return entry.actor_key == wanted or (":" not in wanted and entry.actor_kind == wanted)


def page(
    core: Any,
    workspace_id: str,
    *,
    level: Literal["all", "problems"] = "all",
    area: Area | None = None,
    q: str = "",
    before: str = "9999",
    limit: int = 100,
    actor: str = "",
    since: str = "",
    until: str = "",
) -> LogPage:
    """One page of the workspace's Log, newest first, with the page's filters."""
    require_workspace(core, workspace_id)
    entries = _entries(core, workspace_id, before)
    day_ago = log_rows.day_ago(core.db)
    problems_24h = sum(e.level == "error" and e.at >= day_ago for e in entries)
    actors = _actors(entries)
    if level == "problems":
        entries = [e for e in entries if e.level in ("warn", "error")]
    if area:
        entries = [e for e in entries if e.area == area]
    if actor:
        entries = [e for e in entries if _actor_matches(e, actor)]
    if since.strip():
        entries = [e for e in entries if e.at >= since.strip()]
    if until.strip():
        # A day includes all of it ("2026-10-27" < "2026-10-27T…" < "2026-10-27~").
        end = until.strip() + ("~" if len(until.strip()) == 10 else "")
        entries = [e for e in entries if e.at <= end]
    if q.strip():
        needle = q.strip().lower()
        entries = [
            e for e in entries if needle in f"{e.where} {e.text} {e.cause} {e.actor}".lower()
        ]
    entries.sort(key=lambda e: (e.at, e.id), reverse=True)
    return LogPage(
        entries=entries[:limit], problems_24h=problems_24h, more=len(entries) > limit, actors=actors
    )
