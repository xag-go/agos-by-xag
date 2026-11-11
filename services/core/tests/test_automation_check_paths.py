"""Check before save, through the real paths: the owner's API (a save that is refused
lists every problem; the dry-run endpoint) and the Co-Founder (a refused create comes back
with the list, a saved one answers with how it runs, check_automation saves nothing)."""

from typing import Any

from test_automation_team import MONDAY_STEPS, create, team  # noqa: F401  (fixtures)
from test_cofounder_actions import _run
from work_env import MODEL, env, fake_board  # noqa: F401  (fixtures)

from agos_core.actions import hermes_channel

BROKEN = [
    {"key": "a", "title": "First", "agent": "researcher", "waits_on": ["b"]},
    {"key": "b", "title": "Second", "agent": "ghost", "waits_on": ["a"]},
]


def _body(ws: str, **extra: Any) -> dict[str, Any]:
    return {
        "name": "Check me",
        "instructions": "Do the work.",
        "schedule": "0 9 * * 1",
        "model": MODEL,
        "on": True,
        **extra,
    }


def test_a_refused_save_lists_every_problem_and_saves_nothing(team: Any) -> None:  # noqa: F811
    client, _, _core, ws = team
    r = client.post(f"/workspaces/{ws}/automations", json=_body(ws, steps=BROKEN, schedule=""))
    assert r.status_code == 400, r.text
    text = r.text
    assert "Fix these 3 things first" in text  # cycle, unknown agent, nothing starts it
    assert "wait on each other in a circle" in text and "@ghost" in text
    assert "Nothing starts it" in text
    assert client.get(f"/workspaces/{ws}/automations").json() == []


def test_the_dry_run_says_how_it_will_run_and_writes_nothing(team: Any) -> None:  # noqa: F811
    client, _, _core, ws = team
    r = client.post(f"/workspaces/{ws}/automations/check", json=_body(ws, steps=MONDAY_STEPS))
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["problems"] == []
    lines = got["preview"].splitlines()
    assert lines[0].startswith("Starts ")
    assert [line[:2] for line in lines[1:4]] == ["1)", "2)", "3)"]
    assert "Researcher" in lines[1] and "Ideas" in lines[2] and "checks" in lines[3]
    assert client.get(f"/workspaces/{ws}/automations").json() == []
    bad = client.post(f"/workspaces/{ws}/automations/check", json=_body(ws, steps=BROKEN)).json()
    assert len(bad["problems"]) == 2 and bad["preview"] == ""


def test_steps_saved_out_of_order_are_stored_after_what_they_wait_on(team: Any) -> None:  # noqa: F811
    client, _, _core, ws = team
    steps = [MONDAY_STEPS[1], MONDAY_STEPS[0]]  # "ideas" waits on "research", listed first
    aid = create(client, ws, steps=steps)
    saved = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert [s["key"] for s in saved["steps"]] == ["research", "ideas"]


def test_the_cofounder_gets_all_problems_back_and_no_card_is_made(team: Any) -> None:  # noqa: F811
    _client, _, core, ws = team
    said = hermes_channel.run_actions(
        core,
        ws,
        "kanban:t_e545e37b",
        [
            {
                "do": "create_automation",
                "name": "Broken",
                "instructions": "x",
                "schedule": "0 9 * * 1",
                "steps": BROKEN,
            }
        ],
    )
    [result] = said["results"]
    assert result["status"] == "failed"
    assert "wait on each other in a circle" in result["error"] and "@ghost" in result["error"]


def test_a_saved_cofounder_automation_answers_with_how_it_runs(team: Any) -> None:  # noqa: F811
    _client, _, core, ws = team
    [made] = _run(
        core,
        ws,
        {
            "do": "create_automation",
            "name": "Monday ideas",
            "schedule": "0 9 * * 1",
            "instructions": "Ideas.",
            "steps": MONDAY_STEPS,
        },
    )
    assert made["status"] == "done", made
    import json

    result = json.loads(
        core.db.execute(
            "SELECT result FROM cofounder_actions WHERE id = ?", (made["id"],)
        ).fetchone()["result"]
    )
    assert result["report"].startswith("Starts ") and "1) " in result["report"]
    [changed] = _run(
        core, ws, {"do": "update_automation", "automation": "Monday ideas", "schedule": "0 8 * * 1"}
    )
    again = json.loads(
        core.db.execute(
            "SELECT result FROM cofounder_actions WHERE id = ?", (changed["id"],)
        ).fetchone()["result"]
    )
    assert "1) " in again["report"]


def test_check_automation_is_a_dry_run_that_saves_nothing(team: Any) -> None:  # noqa: F811
    client, _, core, ws = team
    import json

    def report(item: dict[str, Any]) -> str:
        [card] = _run(core, ws, item)
        assert card["status"] == "done", card
        return str(
            json.loads(
                core.db.execute(
                    "SELECT result FROM cofounder_actions WHERE id = ?", (card["id"],)
                ).fetchone()["result"]
            )["report"]
        )

    bad = report(
        {
            "do": "check_automation",
            "name": "B",
            "instructions": "x",
            "schedule": "",
            "steps": BROKEN,
        }
    )
    assert bad.startswith("Would NOT be saved") and "circle" in bad and "Nothing starts it" in bad
    good = report(
        {
            "do": "check_automation",
            "name": "G",
            "instructions": "x",
            "schedule": "0 9 * * 1",
            "steps": MONDAY_STEPS,
        }
    )
    assert good.startswith("Nothing is saved. It would be accepted.") and "1) " in good
    assert client.get(f"/workspaces/{ws}/automations").json() == []


def test_variables_sent_by_the_owner_count_and_missing_ones_are_named(team: Any) -> None:  # noqa: F811
    client, _, _core, ws = team
    steps = [{"key": "s", "title": "Find {topic}", "agent": "researcher", "description": "{x}"}]
    body = _body(ws, steps=steps, variables=[{"name": "topic", "default": "Argan"}])
    r = client.post(f"/workspaces/{ws}/automations", json=body)
    assert r.status_code == 400 and "uses {x}, but" in r.text and "uses {topic}" not in r.text
    steps[0]["description"] = "{topic} and {run.date}"
    assert client.post(f"/workspaces/{ws}/automations", json=body).status_code == 201
