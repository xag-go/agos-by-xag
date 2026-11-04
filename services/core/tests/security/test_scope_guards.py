"""Workspaces are fully isolated: workspace A's routes never read or change workspace B's
rows, whatever ids A sends. Each probe proves the guard the workspace-scope scan credits
(a scoped load before the by-id write: automations `repo.row`, vision `_one` /
`_one_result`, Skill Studio `_row` + `_input`, watchdogs `_row`, status cards `_row`)."""

from typing import Any

import pytest
from test_library import MODEL, env, skill, ws  # noqa: F401 - fixture

from agos_core.db import automations as automation_rows
from agos_core.db import skill_tests as test_rows
from agos_core.db import sql, status_cards
from agos_core.db import watchdogs as watchdog_rows
from agos_core.domain.models import ModelSelection

# Every table a probe below could touch, read whole for B before and after.
TABLES = (
    "automations",
    "automation_revisions",
    "goals",
    "key_results",
    "skill_test_inputs",
    "kanban_watchdogs",
    "status_cards",
)


def _rows_of(core: Any, workspace_id: str) -> dict[str, list[tuple[Any, ...]]]:
    return {
        t: [
            tuple(r)
            for r in core.db.execute(
                sql.text(
                    "SELECT * FROM {t} WHERE workspace_id = ? ORDER BY 1", t=sql.name(t, TABLES)
                ),
                (workspace_id,),
            )
        ]
        for t in TABLES
    }


@pytest.fixture
def two(env: Any) -> Any:  # noqa: F811
    client, core, _runner, _home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    theirs: dict[str, int] = {}
    theirs["automation"] = automation_rows.insert_automation(
        core.db,
        b,
        name="Their report",
        file="automations/their-report.md",
        schedule="",
        model=ModelSelection.model_validate(MODEL),
    )
    core.db.execute(
        "INSERT INTO automation_revisions (workspace_id, automation_id, n, snapshot, who,"
        " summary, created_at) VALUES (?, ?, 1, '{}', 'owner', 'saved', '2026-11-04')",
        (b, theirs["automation"]),
    )
    theirs["skill"] = skill(client, b)
    theirs["input"] = test_rows.add_input(core.db, b, theirs["skill"], "case", "text", "out")
    assert client.put(f"/workspaces/{b}/vision", json={"title": "Their vision"}).status_code < 300
    goal = client.post(f"/workspaces/{b}/vision/goals", json={"title": "Their goal"})
    theirs["goal"] = int(goal.json()["id"])
    result = client.post(
        f"/workspaces/{b}/vision/goals/{theirs['goal']}/results", json={"title": "KR"}
    )
    theirs["result"] = int(result.json()["id"])
    watchdog_rows.add(core.db, b, "t_theirs01", "2026-11-04T00:00:00.000Z")
    theirs["watchdog"] = int(watchdog_rows.by_card(core.db, b, "t_theirs01")["id"])  # type: ignore[index]
    theirs["status"] = status_cards.add(core.db, b, "Their status", "workspace", "", "manual")
    return client, core, a, b, theirs


def test_workspace_a_never_touches_workspace_bs_rows_by_id(two: Any) -> None:
    client, core, a, b, theirs = two
    mine = skill(client, a)
    before = _rows_of(core, b)
    auto, item, inp = theirs["automation"], theirs["skill"], theirs["input"]
    probes = [
        ("get", f"/automations/{auto}", None),
        (
            "put",
            f"/automations/{auto}",
            {
                "name": "Mine now",
                "instructions": "x",
                "schedule": "",
                "model": MODEL,
                "on": True,
                "hook": True,
            },
        ),
        ("get", f"/automations/{auto}/revisions", None),
        ("post", f"/automations/{auto}/revisions/1/restore", None),
        ("post", f"/automations/{auto}/toggle", {"on": False}),
        ("post", f"/automations/{auto}/run", {}),
        ("delete", f"/automations/{auto}", None),
        ("put", f"/skills/{item}/tests/inputs/{inp}", {"name": "n", "text": "t", "expected": ""}),
        ("delete", f"/skills/{item}/tests/inputs/{inp}", None),
        # A's own skill with B's input id: the input must be that skill's.
        ("put", f"/skills/{mine}/tests/inputs/{inp}", {"name": "n", "text": "t", "expected": ""}),
        ("delete", f"/skills/{mine}/tests/inputs/{inp}", None),
        ("put", f"/vision/items/{theirs['goal']}", {"title": "Mine now"}),
        ("delete", f"/vision/items/{theirs['goal']}", None),
        ("post", f"/vision/goals/{theirs['goal']}/results", {"title": "Mine"}),
        ("put", f"/vision/results/{theirs['result']}", {"current": 9}),
        ("delete", f"/vision/results/{theirs['result']}", None),
        ("post", f"/watchdogs/{theirs['watchdog']}/observe", {"fingerprint": "t_x:1"}),
        ("put", f"/status-cards/{theirs['status']}", {"title": "Mine now"}),
        ("post", f"/status-cards/{theirs['status']}/refresh", None),
        ("delete", f"/status-cards/{theirs['status']}", None),
    ]
    answered = {}
    for verb, path, body in probes:
        kw = {"json": body} if body is not None else {}
        r = getattr(client, verb)(f"/workspaces/{a}{path}", **kw)
        answered[f"{verb} {path}"] = r.status_code
    allowed = {f"{v} {p}": s for (v, p, _b), s in zip(probes, answered.values(), strict=True)}
    # A delete is idempotent (a gone id answers like a missing one); B's rows stay below.
    wrong = {
        k: s
        for k, s in allowed.items()
        if s not in (404, 409, 422) and not (k.startswith("delete ") and s in (200, 204))
    }
    assert not wrong, wrong
    assert _rows_of(core, b) == before
