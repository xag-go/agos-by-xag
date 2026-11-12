"""The Co-Founder looks for gaps against the goals and proposes a hire (weekly
review and heartbeat), and older heartbeat jobs get the new prompt at start."""

from __future__ import annotations

from typing import Any

from test_automation_team import team  # noqa: F401  (fixture)
from work_env import Env, agent, env, fake_board  # noqa: F401  (fixtures)

from agos_core.actions import heartbeat, rhythm
from agos_core.actions.services.system import startup
from agos_core.engine.cron import JobSpec


def _jobs_in(core: Any, home: str) -> list[dict[str, Any]]:
    return [j for j in core.engine.cron_bridge.jobs.values() if j["home"] == home]


def test_the_weekly_review_looks_for_gaps_and_proposes_one_hire() -> None:
    weekly = rhythm.PROMPTS["weekly"]
    gaps = weekly.index("4. Gaps:")
    assert gaps < weekly.index("5. Read the team scorecards") < weekly.index("6. Post the review")
    step = weekly[gaps : weekly.index("5. Read the team scorecards")]
    assert "team-design skill" in step and "reports_to" in step
    assert "ONE hire with agos_propose kind hire" in step
    assert "why no member covers" in step and "still waits for the owner" in step


def test_only_the_cofounders_heartbeat_looks_for_gaps() -> None:
    cofounder = heartbeat.prompt_for(None, cofounder_lines=True)
    member = heartbeat.prompt_for("researcher", cofounder_lines=False)
    assert "7. A goal, key result or project whose work no member's role covers" in cofounder
    assert "agos_propose kind hire" in cofounder and "team-design skill" in cofounder
    assert "propose nothing more" in cofounder
    assert "no member's role covers" not in member
    # The cheap no-work ending stays last.
    assert cofounder.rstrip().endswith("this run must stay cheap.")


def test_an_older_heartbeat_prompt_is_refreshed_at_start_with_interval_and_pause_kept(
    team: Env,  # noqa: F811
) -> None:
    client, _fake, core, ws = team
    from agos_core.actions import agent_profiles
    from agos_core.actions import team as team_actions

    root_home = str(core.engine.profile_home(ws))
    member_home = str(core.engine.profile_home(agent_profiles.key(ws, "researcher")))
    assert client.put(f"/workspaces/{ws}/heartbeats/cofounder", json={"on": True, "interval": "4h"})
    assert client.put(
        f"/workspaces/{ws}/heartbeats/researcher", json={"on": True, "interval": "1h"}
    ).is_success
    team_actions.park(core, ws, "researcher", True)
    for home in (root_home, member_home):
        (job,) = _jobs_in(core, home)
        job["spec"] = JobSpec(**{**job["spec"].as_dict(), "prompt": "an older AGOS's text"})
    assert heartbeat.refresh_all(core) == 2
    (root_job,) = _jobs_in(core, root_home)
    assert root_job["spec"].prompt == heartbeat.prompt_for(None, cofounder_lines=True)
    assert root_job["spec"].schedule == "4h" and root_job["enabled"] is True
    (member_job,) = _jobs_in(core, member_home)
    assert member_job["spec"].prompt == heartbeat.prompt_for("researcher", cofounder_lines=False)
    assert member_job["spec"].schedule == "1h"
    assert member_job["enabled"] is False
    assert member_job["paused_reason"] == heartbeat.PARKED_REASON
    assert heartbeat.refresh_all(core) == 0  # already current: nothing edited


def test_a_custom_schedule_is_left_alone(team: Env) -> None:  # noqa: F811
    client, _fake, core, ws = team
    root_home = str(core.engine.profile_home(ws))
    client.put(f"/workspaces/{ws}/heartbeats/cofounder", json={"on": True, "interval": "4h"})
    (job,) = _jobs_in(core, root_home)
    job["spec"] = JobSpec(**{**job["spec"].as_dict(), "prompt": "old", "schedule": "7h"})
    assert heartbeat.refresh_all(core) == 0
    assert _jobs_in(core, root_home)[0]["spec"].prompt == "old"


def test_the_refresh_runs_at_start() -> None:
    assert (heartbeat, "refresh_all", "heartbeat job prompts not refreshed") in startup._SKILLS
