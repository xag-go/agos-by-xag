"""Automations under the account pause: Hermes's own pause is the account pause, an old
pause is put back once at start, and an automation turned off while held stays off.

Split out of test_automations.py (saving, syncing and reading runs stay there)."""

import json
from typing import Any

from test_automations import env, new  # noqa: F401


def test_the_account_pause_is_hermes_own_pause(env: Any) -> None:  # noqa: F811
    from agos_core.actions import account_pause

    client, core, cron, ws = env
    on = new(client, ws)
    off = new(client, ws, name="Off one")
    client.post(f"/workspaces/{ws}/automations/{off}/toggle", json={"on": False})
    sentinel = core.engine.profile_home(ws) / "ESTOP"
    assert account_pause.apply(core, "Claude current week at 92%") == [ws]
    # Hermes's own pause: the root's ESTOP sentinel with AGOS's reason. Hermes
    # itself holds its cron, its Kanban dispatcher and new turns off that file.
    body = json.loads(sentinel.read_text())
    assert body["reason"] == "Account pause in AGOS: Claude current week at 92%"
    # Nothing else is flipped: the profile sync's dispatch list stays the true
    # one (never emptied by the pause), and the jobs keep their own state.
    profile = core.engine.profile(ws)
    assert core.engine.runner.config[profile]["kanban.dispatch_profiles"] != "[]"
    jobs = {j["spec"].name: j for j in cron.jobs.values()}
    assert jobs["Daily brief"]["enabled"] is True
    assert jobs["Off one"]["paused_reason"] == "Turned off in AGOS"
    got = client.get(f"/workspaces/{ws}/automations/{on}").json()
    assert got["on"] is True and got["problem"].startswith("Waits:")
    assert account_pause.apply(core, "Claude current week at 92%") == []  # already held
    # A profile sync while held writes the true list (the sentinel holds the board).
    from agos_core.actions import agent_profiles

    pairs = agent_profiles.kanban_pairs(core, ws, cofounder=True)
    assert "default" in pairs["kanban.dispatch_profiles"]
    # Under the line again: AGOS's own pause goes.
    assert account_pause.apply(core, None) == [ws]
    assert not sentinel.exists()
    assert account_pause.apply(core, None) == []  # nothing to resume
    # The owner's own pause is never AGOS's to lift: `touch ESTOP` (fail safe,
    # no body) and a hand-written reason both stay exactly as he made them.
    sentinel.write_text("")
    assert account_pause.apply(core, None) == []
    assert sentinel.exists()
    sentinel.write_text(json.dumps({"reason": "mine"}))
    assert account_pause.apply(core, None) == []
    # And while he holds the root himself, AGOS never pauses over him.
    assert account_pause.apply(core, "Claude at 99%") == []
    assert json.loads(sentinel.read_text())["reason"] == "mine"
    sentinel.unlink()


def test_the_old_pause_is_put_back_once_at_start(env: Any) -> None:  # noqa: F811
    from agos_core.actions import account_pause

    client, core, cron, ws = env
    new(client, ws)
    # What the pre-Step-33 pause left behind: an emptied dispatch list in the
    # root's config and a job held with its reason.
    config = core.engine.profile_home(ws) / "config.yaml"
    config.write_text("kanban:\n  dispatch_profiles: []\n")
    job = next(iter(cron.jobs))
    cron.pause(core.engine.profile_home(ws), job, "Account pause in AGOS")
    assert account_pause.move_old_pause(core) == 2
    profile = core.engine.profile(ws)
    assert "default" in core.engine.runner.config[profile]["kanban.dispatch_profiles"]
    assert cron.jobs[job]["enabled"] is True
    # Idempotent: the config write isn't visible to the fake's file, so only the
    # job move counts as done; a job already enabled is never touched again.
    config.write_text("kanban:\n  dispatch_profiles:\n    - x\n")  # Hermes's list
    assert account_pause.move_old_pause(core) == 0


def test_turned_off_while_held_stays_off(env: Any) -> None:  # noqa: F811
    from agos_core.actions import account_pause

    client, _core, cron, ws = env
    aid = new(client, ws)
    account_pause.apply(_core, "Claude at 95%")
    client.post(f"/workspaces/{ws}/automations/{aid}/toggle", json={"on": False})
    assert cron.jobs["job1"]["paused_reason"] == "Turned off in AGOS"
    account_pause.apply(_core, None)
    assert cron.jobs["job1"]["enabled"] is False
