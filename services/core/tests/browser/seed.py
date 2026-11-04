"""What the light rig's workspace holds before the browser tests click (tests/browser).

Everything goes through AGOS's own API (or, for what only Hermes makes, the suite's
fakes of it), so each page renders its real parts: cards on the board, a goal tree, a
chat with an answer, an automation, a proposal waiting in the Inbox, a team member.
A step that fails is printed and the rest go on: the screen tests then show it.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from test_proposals import WHOLE, _card_blocks, _settle
from work_env import agent, library_skill

from agos_core.actions import agent_profiles
from agos_core.engine import proposals as proposal_rules

MODEL = {"provider": "claude", "mode": "cli", "model": "claude-sonnet-5", "effort": "high"}
CARDS = ("Write the launch post", "Fix the login bug", "Plan Q1 hiring")


def _step(done: dict[str, Any], name: str, run: Callable[[], Any]) -> Any:
    try:
        value = run()
    except Exception as error:  # noqa: BLE001 - one seed step failing leaves the others
        print(f"seed {name} FAILED: {type(error).__name__}: {error}", flush=True)
        done.setdefault("failed", []).append(name)
        return None
    return value


def _ok(answer: Any) -> Any:
    if answer.status_code >= 400:
        raise RuntimeError(
            f"{answer.request.method} {answer.request.url}: {answer.status_code} {answer.text[:300]}"
        )
    return answer.json() if answer.content else None


def seed(client: Any, core: Any, ws: str) -> dict[str, Any]:
    """Seed workspace `ws`; returns what the tests need to find it again."""
    done: dict[str, Any] = {}
    w = f"/workspaces/{ws}"
    _step(done, "member", lambda: agent(client, ws, "writer"))
    _step(done, "skill", lambda: library_skill(core, ws))
    _step(
        done,
        "vision",
        lambda: _ok(
            client.put(
                w + "/vision",
                json={
                    "title": "Ship the best agent OS",
                    "why": "Owners save hours.",
                    "strategy": "Small steps.",
                },
            )
        ),
    )
    goal = _step(
        done,
        "goal",
        lambda: _ok(
            client.post(
                w + "/vision/goals",
                json={
                    "title": "Grow to 100 owners",
                    "why": "Prove it works",
                    "dueOn": "2026-12-31",
                },
            )
        ),
    )
    gid = (goal or {}).get("id")
    if gid:
        _step(
            done,
            "result",
            lambda: _ok(
                client.post(
                    f"{w}/vision/goals/{gid}/results",
                    json={
                        "title": "Paying owners",
                        "start": 0,
                        "current": 12,
                        "target": 100,
                        "unit": "owners",
                    },
                )
            ),
        )
        _step(
            done,
            "project",
            lambda: _ok(
                client.post(
                    f"{w}/vision/goals/{gid}/projects",
                    json={"title": "Launch site", "why": "People find us"},
                )
            ),
        )
    _step(
        done,
        "label",
        lambda: _ok(client.post(w + "/labels", json={"name": "urgent", "color": "red"})),
    )

    def card(title: str) -> Any:
        body = {"title": title, "body": "Details for " + title, "member": "", "triage": False}
        return _ok(client.post(w + "/kanban", json=body))

    cards = []
    for title in CARDS:
        made = _step(done, f"card {title}", functools.partial(card, title))
        if made:
            cards.append(made.get("id") or made.get("card"))
    done["cards"] = cards
    automation = _step(
        done,
        "automation",
        lambda: _ok(
            client.post(
                w + "/automations",
                json={
                    "name": "Daily brief",
                    "instructions": "Summarise the day.",
                    "schedule": "0 8 * * *",
                    "model": MODEL,
                    "on": True,
                },
            )
        ),
    )
    done["automation"] = (automation or {}).get("id")
    chat = _step(
        done, "chat", lambda: _ok(client.post(w + "/chats", json={"title": "Planning chat"}))
    )
    done["chat"] = (chat or {}).get("id")

    def proposal(kind: str, payload: dict[str, Any], words: str) -> str:
        card = _card_blocks(core, ws, words + "\n\n" + proposal_rules.block(kind, payload))
        _settle(core, ws, card)
        # _card_blocks left a bare board file for the hook's read; without it AGOS reads
        # every card through the (fake) Hermes CLI, which knows them all.
        (agent_profiles.board_home(core, ws) / "kanban.db").unlink(missing_ok=True)
        return card

    plan = {"title": "Launch plan", "markdown": "# Launch\n\n1. Site\n2. Post"}
    # A hire names the goal it serves once the workspace has goals.
    hire = {**WHOLE, "goal_id": gid} if gid else WHOLE
    done["plan_card"] = _step(
        done, "plan proposal", lambda: proposal("plan", plan, "A plan for the launch.")
    )
    done["hire_card"] = _step(
        done, "hire proposal", lambda: proposal("hire", hire, "I'd hire a script writer.")
    )
    print("seeded:", done, flush=True)
    return done
