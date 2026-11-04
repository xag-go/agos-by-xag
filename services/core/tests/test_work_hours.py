"""Work hours (Settings → Work hours): the week and its timezone math, who is on,
check-out (idle stops, a busy agent finishes its card, parked at +2 h), cron held
off-hours and resumed at check-in, the dispatcher's list, the check-in wake and
note, messages held until check-in, Wake now, and each workspace on its own."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from test_automation_team import team
from work_env import Env, create_ws, env, fake_board  # noqa: F401  (fixtures)

from agos_core.actions import heartbeat, hermes_channel, work_hours
from agos_core.actions.errors import ActionError
from agos_core.engine.cron import WORK_HOURS_REASON

team = team  # the team fixture (researcher + ideas), with a FakeCron

UTC_ZONE = ZoneInfo("UTC")
WEEK = {
    "mon": {"from": "09:00", "to": "18:00"},
    "tue": {"from": "09:00", "to": "18:00"},
    "wed": {"from": "09:00", "to": "18:00"},
    "thu": {"from": "09:00", "to": "18:00"},
    "fri": {"from": "22:00", "to": "06:00"},  # overnight: ends Saturday morning
    "sat": None,
    "sun": None,
}
# 2026-11-02 is a Monday.
MON_10 = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
MON_19 = datetime(2026, 11, 2, 19, 0, tzinfo=UTC)


# ---- the week -------------------------------------------------------------------------


def test_a_week_is_checked_and_off_days_are_none() -> None:
    clean = work_hours.clean({"on": True, "days": WEEK})
    assert clean["on"] is True and clean["days"]["sat"] is None
    assert clean["days"]["fri"] == {"from": "22:00", "to": "06:00"}
    with pytest.raises(ActionError, match="Mon: from is a time like 09:00"):
        work_hours.clean({"on": True, "days": {**WEEK, "mon": {"from": "9am", "to": "18:00"}}})
    with pytest.raises(ActionError, match="Tue: from and to are the same time"):
        work_hours.clean({"on": True, "days": {**WEEK, "tue": {"from": "09:00", "to": "09:00"}}})
    with pytest.raises(ActionError, match="Wed: to is a time like"):
        work_hours.clean({"on": True, "days": {**WEEK, "wed": {"from": "09:00", "to": "24:00"}}})
    # Nothing given: Mon-Fri 09:00-18:00, the weekend OFF, the hours off.
    default = work_hours.clean({})
    assert default["on"] is False and default["days"]["mon"] == {"from": "09:00", "to": "18:00"}
    assert default["days"]["sun"] is None


def test_shifts_follow_the_owners_zone_overnight_ranges_and_off_days() -> None:
    days = work_hours.clean({"on": True, "days": WEEK})["days"]
    assert work_hours.open_shift(days, UTC_ZONE, MON_10) is not None
    assert work_hours.open_shift(days, UTC_ZONE, MON_19) is None
    # Check-in after Monday's check-out: Tuesday 09:00.
    assert work_hours.next_check_in(days, UTC_ZONE, MON_19) == datetime(2026, 11, 3, 9, tzinfo=UTC)
    assert work_hours.last_check_out(days, UTC_ZONE, MON_19) == datetime(
        2026, 11, 2, 18, tzinfo=UTC
    )
    # Friday 22:00 → Saturday 06:00, then the weekend is OFF: next check-in Monday 09:00.
    sat_3 = datetime(2026, 11, 7, 3, tzinfo=UTC)
    assert work_hours.open_shift(days, UTC_ZONE, sat_3) == (
        datetime(2026, 11, 6, 22, tzinfo=UTC),
        datetime(2026, 11, 7, 6, tzinfo=UTC),
    )
    assert work_hours.next_check_in(days, UTC_ZONE, sat_3) == datetime(2026, 11, 9, 9, tzinfo=UTC)
    # The owner's clock: 09:00 in New York is 14:00 UTC in November (after DST ends),
    # 13:00 UTC in October (still on daylight time).
    ny = ZoneInfo("America/New_York")
    assert work_hours.next_check_in(days, ny, MON_10) == datetime(2026, 11, 2, 14, tzinfo=UTC)
    oct_mon = datetime(2026, 10, 26, 10, tzinfo=UTC)
    assert work_hours.next_check_in(days, ny, oct_mon) == datetime(2026, 10, 26, 13, tzinfo=UTC)
    # Casablanca (UTC+1): Monday 18:30 UTC is 19:30 there, off.
    casa = ZoneInfo("Africa/Casablanca")
    assert work_hours.open_shift(days, casa, datetime(2026, 11, 2, 18, 30, tzinfo=UTC)) is None


# ---- who is on --------------------------------------------------------------------------


def _hours(client: Any, ws: str, on: bool = True, days: dict[str, Any] | None = None) -> Any:
    r = client.put(f"/workspaces/{ws}/work-hours", json={"on": on, "days": days or WEEK})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[datetime]:
    """The owner's time now (UTC zone), and the owner's changes applied inline."""
    now = [MON_10]
    monkeypatch.setattr(work_hours, "clock", lambda: now[0])
    monkeypatch.setattr(work_hours, "_run_later", lambda fn: None)
    return now


def test_off_by_default_and_stay_on_today_clears_at_the_next_check_in(
    team: Env, clock: list[datetime]
) -> None:
    client, _fake, core, ws = team
    view = client.get(f"/workspaces/{ws}/work-hours").json()
    assert view["on"] is False and view["zone"] == "UTC"
    assert all(a["state"] is None for a in view["agents"])  # always on, as before
    assert work_hours.wanted_on(core, ws, "researcher", MON_19)
    _hours(client, ws)
    assert work_hours.wanted_on(core, ws, "researcher", MON_10)
    assert not work_hours.wanted_on(core, ws, "researcher", MON_19)
    assert not work_hours.wanted_on(core, ws, "", MON_19)  # the Co-Founder follows them too
    clock[0] = MON_19
    r = client.put(f"/workspaces/{ws}/work-hours/stay", json={"agents": ["researcher"]})
    assert r.status_code == 200, r.text
    assert r.json()["stay"] == ["researcher"] and r.json()["stayUntil"] == "2026-11-03T09:00:00Z"
    states = {a["agent"]: a["state"] for a in r.json()["agents"]}
    assert states == {"": "off", "researcher": "staying", "ideas": "off"}
    assert work_hours.wanted_on(core, ws, "researcher", MON_19 + timedelta(hours=10))
    # At the next check-in the pick is gone by itself.
    tue_9 = datetime(2026, 11, 3, 9, tzinfo=UTC)
    assert work_hours.stay_agents(work_hours._stored(core, ws), tue_9) == []
    assert not work_hours.wanted_on(core, ws, "researcher", tue_9 + timedelta(hours=10))
    # Someone not on the team is refused; nobody = an empty pick.
    bad = client.put(f"/workspaces/{ws}/work-hours/stay", json={"agents": ["ghost"]})
    assert bad.status_code == 400 and "isn't on this workspace's team" in bad.json()["detail"]
    assert client.put(f"/workspaces/{ws}/work-hours/stay", json={"agents": []}).json()["stay"] == []
    # A bad week is refused with the day's words.
    r = client.put(
        f"/workspaces/{ws}/work-hours",
        json={"on": True, "days": {**WEEK, "mon": {"from": "25:00", "to": "18:00"}}},
    )
    assert r.status_code == 400 and r.json()["detail"].startswith("Mon:")


# ---- check-out / check-in on Hermes's switches -----------------------------------------


class Board:
    """Hermes's board as work_hours reads (cards) and writes it (its Kanban CLI)."""

    def __init__(self) -> None:
        self.cards: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, ...]] = []

    def read(self, core: Any, ws: str) -> list[dict[str, Any]]:
        return [dict(c) for c in self.cards.values() if c["status"] not in ("done", "archived")]

    def cli(self, core: Any, ws: str, *args: str) -> bool:
        self.calls.append(args)
        card = self.cards.get(args[1]) if len(args) > 1 else None
        if card is None:
            return False
        if args[0] == "reclaim":
            card["status"] = "ready"
        elif args[0] == "schedule":
            card.update(status="scheduled", parked=args[2] == work_hours.PARK_REASON)
        elif args[0] == "unblock":
            card.update(status="ready", parked=False)
        return True


@pytest.fixture
def board(monkeypatch: pytest.MonkeyPatch) -> Board:
    found = Board()
    monkeypatch.setattr(work_hours, "cards", found.read)
    monkeypatch.setattr(work_hours, "kanban", found.cli)
    return found


@pytest.fixture
def dispatch(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from agos_core.actions import hire_kit
    from agos_core.actions.services.hire import kit_files as hire_kit_files

    synced: list[str] = []

    def sync(core: Any, ws: str) -> bool:
        synced.append(ws)
        return True

    # work_hours looks it up in the facade, the hire service in kit_files.
    for mod in (hire_kit, hire_kit_files):
        monkeypatch.setattr(mod, "sync_dispatch", sync)
    return synced


def _names(core: Any, ws: str) -> list[str]:
    import json

    from agos_core.actions import agent_profiles

    return list(json.loads(agent_profiles.dispatch_list(core, ws)))


def test_check_out_idle_stops_busy_finishes_then_parks_and_check_in_goes_on(
    team: Env, clock: list[datetime], board: Board, dispatch: list[str]
) -> None:
    client, _fake, core, ws = team
    cron = core.engine.cron_bridge
    woken: list[tuple[str, str | None]] = []
    cron.run_now = lambda home, job_id, prompt=None: woken.append((job_id, prompt))
    client.put(f"/workspaces/{ws}/heartbeats/researcher", json={"on": True, "interval": "1h"})
    client.put(f"/workspaces/{ws}/heartbeats/ideas", json={"on": True, "interval": "4h"})
    jobs = {j["spec"].name + "@" + j["home"].rsplit("/", 1)[-1]: j for j in cron.jobs.values()}
    researcher_beat = next(j for k, j in jobs.items() if "a-researcher" in k)
    ideas_beat = next(j for k, j in jobs.items() if "a-ideas" in k)
    board.cards["t_busy"] = {
        "id": "t_busy",
        "status": "running",
        "assignee": "a-ideas",
        "parked": False,
    }
    board.cards["t_wait"] = {
        "id": "t_wait",
        "status": "ready",
        "assignee": "a-researcher",
        "parked": False,
    }
    _hours(client, ws)
    assert work_hours.apply(core, ws, MON_10) == {"": "on", "researcher": "on", "ideas": "on"}
    assert sorted(_names(core, ws)) == ["a-ideas", "a-researcher", "default"]

    # 19:00, past Monday's check-out: the idle researcher is off at once, ideas
    # finishes its running card (told to on the card: Hermes injects it mid-run).
    clock[0] = MON_19
    assert work_hours.apply(core, ws, MON_19) == {
        "": "off",
        "researcher": "off",
        "ideas": "closing",
    }
    assert dispatch == [ws] and _names(core, ws) == []  # Hermes's dispatcher claims nothing
    assert (
        researcher_beat["enabled"] is False
        and researcher_beat["paused_reason"] == WORK_HOURS_REASON
    )
    assert ideas_beat["paused_reason"] == WORK_HOURS_REASON
    (note,) = [c for c in board.calls if c[0] == "comment"]
    assert note[1] == "t_busy" and note[-2:] == ("--author", work_hours.AUTHOR)
    assert "18:00" in note[2] and "20:00" in note[2] and work_hours.NOTE_MARK in note[2]
    # The heartbeat still reads "on" on the agent card, paused off-hours.
    beat = next(h for h in heartbeat.list_all(core, ws) if h.agent == "researcher")
    assert beat.on and beat.problem and "off-hours" in beat.problem
    view = {a["agent"]: a for a in client.get(f"/workspaces/{ws}/work-hours").json()["agents"]}
    assert view["ideas"]["state"] == "finishing" and view["researcher"]["state"] == "off"
    assert view["researcher"]["untilText"] == "Tue 09:00"
    # A job turned on meanwhile is held again on the next pass.
    researcher_beat.update(enabled=True, paused_reason=None)
    work_hours.apply(core, ws, MON_19 + timedelta(minutes=1))
    assert researcher_beat["paused_reason"] == WORK_HOURS_REASON

    # Check-out + 2 h and still running: Hermes ends the worker and holds the card.
    later = datetime(2026, 11, 2, 20, 1, tzinfo=UTC)
    clock[0] = later
    assert work_hours.apply(core, ws, later)["ideas"] == "off"
    assert ("reclaim", "t_busy", "--reason", work_hours.PARK_REASON) in board.calls
    assert board.cards["t_busy"]["status"] == "scheduled" and board.cards["t_busy"]["parked"]

    # Tuesday 09:00, check-in: jobs back on, heartbeats woken with the check-in note,
    # the parked card told where to go on from and put back on the board.
    tue_9 = datetime(2026, 11, 3, 9, 0, 30, tzinfo=UTC)
    clock[0] = tue_9
    board.calls.clear()
    assert work_hours.apply(core, ws, tue_9) == {"": "on", "researcher": "on", "ideas": "on"}
    assert {j for j, _ in woken} == {researcher_beat["id"], ideas_beat["id"]}
    assert all(
        p and "where-I-stopped notes" in p and "never start one twice" in p for _, p in woken
    )
    assert board.calls[0][:2] == ("comment", "t_busy") and board.calls[0][-1] == work_hours.AUTHOR
    assert work_hours.NOTE_MARK in board.calls[0][2]
    assert ("unblock", "t_busy") in board.calls
    assert board.cards["t_busy"]["status"] == "ready"
    assert ("unblock", "t_wait") not in board.calls  # never parked: left as it was
    assert sorted(_names(core, ws)) == ["a-ideas", "a-researcher", "default"]
    # Once on, a pass changes nothing.
    board.calls.clear()
    work_hours.apply(core, ws, tue_9 + timedelta(minutes=5))
    assert board.calls == []


def test_a_card_finished_before_the_limit_ends_the_day_without_a_park(
    team: Env, clock: list[datetime], board: Board, dispatch: list[str]
) -> None:
    client, _fake, core, ws = team
    board.cards["t_x"] = {"id": "t_x", "status": "running", "assignee": "a-ideas", "parked": False}
    _hours(client, ws)
    clock[0] = MON_19
    assert work_hours.apply(core, ws, MON_19)["ideas"] == "closing"
    board.cards["t_x"]["status"] = "done"
    assert work_hours.apply(core, ws, MON_19 + timedelta(minutes=20))["ideas"] == "off"
    assert not [c for c in board.calls if c[0] in ("reclaim", "schedule")]
    # Turning the hours off puts everyone back on (today's behaviour).
    _hours(client, ws, on=False)
    assert work_hours.apply(core, ws, MON_19 + timedelta(minutes=30)) == {
        "": "on",
        "researcher": "on",
        "ideas": "on",
    }
    assert work_hours.apply(core, ws, MON_19 + timedelta(minutes=31)) == {}  # nothing to do


def test_automations_show_runs_paused_off_hours(
    team: Env, clock: list[datetime], board: Board, dispatch: list[str]
) -> None:
    from test_automation_team import create

    client, _fake, core, ws = team
    aid = create(client, ws)
    _hours(client, ws)
    clock[0] = MON_19
    work_hours.apply(core, ws, MON_19)
    shown = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert shown["on"] is True and "off-hours" in (shown["problem"] or "")


# ---- messages wait for check-in, Wake now -----------------------------------------------


def _handed(core: Any, ws: str) -> list[Any]:
    return [
        r["taken_at"] or r["done_at"]
        for r in core.db.execute(
            "SELECT taken_at, done_at FROM hermes_inbox WHERE workspace_id = ? AND kind = 'message'",
            (ws,),
        )
    ]


def test_messages_to_an_off_agent_wait_and_wake_now_lets_them_through(
    team: Env, clock: list[datetime], board: Board, dispatch: list[str]
) -> None:
    from agos_core.actions import workers
    from agos_core.db.rows import now

    client, _fake, core, ws = team
    chat = workers.open_dm(core, ws, None)  # the owner's chat with the Co-Founder
    address = f"agos:{chat}"
    _hours(client, ws)
    clock[0] = MON_19
    work_hours.apply(core, ws, MON_19)
    core.db.execute(
        """INSERT INTO hermes_inbox (workspace_id, chat_ref, text, kind, created_at)
           VALUES (?, ?, 'hi', 'message', ?)""",
        (ws, address, now()),
    )
    assert hermes_channel.waits_for_check_in(core, ws, address)
    assert hermes_channel.take_inbox(core, ws, agos=True, members=[""]) == []
    live = client.get(f"/workspaces/{ws}/chats/{chat}/live").json()
    # (the fake gateway asks for its inbox after each request: still nothing for it)
    assert _handed(core, ws) == [None]
    assert live["off"] == {"agent": "", "until": "2026-11-03T09:00:00Z", "untilText": "Tue 09:00"}
    assert work_hours.off_words(live["off"]) == (
        "Off until Tue 09:00 — your message will be answered at check-in."
    )
    # Wake now: on for today (the same as picking it to stay on).
    r = client.post(f"/workspaces/{ws}/work-hours/wake", json={"agent": "cofounder"})
    assert r.status_code == 200 and r.json()["stay"] == [""]
    assert client.get(f"/workspaces/{ws}/chats/{chat}/live").json()["off"] is None
    assert _handed(core, ws) != [None]  # Hermes's gateway took it: it is answered now
    team_view = client.get(f"/workspaces/{ws}/workers").json()
    assert team_view["cofounder"]["shift"] == "staying"
    assert {m["name"]: m["shift"] for m in team_view["members"]} == {
        "researcher": "off",
        "ideas": "off",
    }
    assert work_hours.apply(core, ws, MON_19 + timedelta(minutes=1))[""] == "on"
    assert _names(core, ws) == ["default"]


def test_each_workspace_keeps_its_own_hours(
    team: Env, clock: list[datetime], board: Board, dispatch: list[str]
) -> None:
    client, _fake, core, ws = team
    other = create_ws(client, "Other")
    _hours(client, ws)
    clock[0] = MON_19
    assert work_hours.off_now(core, ws) == {"", "researcher", "ideas"}
    assert work_hours.off_now(core, other) == set()
    assert work_hours.apply(core, other, MON_19) == {}
    assert _names(core, other) == ["default"]
    assert client.get(f"/workspaces/{other}/work-hours").json()["on"] is False


def test_the_cofounder_does_the_same_three_actions(
    team: Env, clock: list[datetime], board: Board, dispatch: list[str]
) -> None:
    from agos_core.actions import cofounder_more

    _client, _fake, core, ws = team
    done = cofounder_more.DOES["set_work_hours"](core, ws, {"on": True, "days": WEEK})
    assert work_hours.schedule(core, ws)["on"] and done["before"]["on"] is False
    clock[0] = MON_19
    stayed = cofounder_more.DOES["stay_on_today"](core, ws, {"agents": ["ideas", "cofounder"]})
    assert sorted(work_hours.view(core, ws)["stay"]) == ["", "ideas"]
    cofounder_more.UNDOES["stay_on_today"](core, ws, stayed)
    assert work_hours.view(core, ws)["stay"] == []
    woke = cofounder_more.DOES["wake_now"](core, ws, {"agent": "@researcher"})
    assert work_hours.view(core, ws)["stay"] == ["researcher"]
    cofounder_more.UNDOES["wake_now"](core, ws, woke)
    cofounder_more.UNDOES["set_work_hours"](core, ws, done)
    assert work_hours.schedule(core, ws)["on"] is False


def test_card_page_leaves_out_the_notes() -> None:
    assert work_hours.hidden_comment({"author": work_hours.AUTHOR, "body": "Check-out"})
    assert work_hours.hidden_comment({"author": "a-ideas", "body": "[where I stopped] half done"})
    assert not work_hours.hidden_comment({"author": "owner", "body": "Looks good"})


def test_the_loop_keeps_each_workspace_with_hours_once_a_minute(
    team: Env, clock: list[datetime], board: Board, dispatch: list[str]
) -> None:
    client, _fake, core, ws = team
    create_ws(client, "Quiet")  # no hours: never looked at
    work_hours._last_check = None
    assert work_hours.keep(core, now=1000.0) == []
    _hours(client, ws)
    work_hours._last_check = None
    clock[0] = MON_19
    assert work_hours.keep(core, now=2000.0) == [ws]
    assert work_hours.keep(core, now=2030.0) == []  # within the minute
    assert work_hours._shift(core, ws)["researcher"]["state"] == "off"
