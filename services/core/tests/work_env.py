"""A workspace with a fake Hermes (its gateway on the agos platform, tests/fake_gateway.py)
for the tests that drive AGOS through its HTTP API."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fake_gateway import follow_requests, pump
from fastapi.testclient import TestClient
from test_engine_sync import FakeRunner

from agos_core.api.app import create_app
from agos_core.config import EngineConfig, Settings
from agos_core.engine.hermes import EngineError, apply_webhook_routes

MODEL = {"provider": "claude", "mode": "cli", "model": "claude-sonnet-5", "effort": "high"}

_LEVELS = ["low", "medium", "high", "none"]
# Hermes's model catalog as api/models.py maps it (the logged-in providers' models).
CATALOG: list[dict[str, Any]] = [
    {
        "id": "claude",
        "label": "Claude",
        "models": [
            {
                "id": m,
                "label": label,
                "modes": ["cli"],
                "efforts": _LEVELS,
                "defaultEffort": "medium",
            }
            for m, label in (
                ("claude-opus-5-5", "Claude Opus 5.5"),
                ("claude-sonnet-5", "Claude Sonnet 5"),
                ("claude-sonnet-4-5", "Claude Sonnet 4.5"),
                ("claude-haiku-4-5-20251001", "Claude Haiku 4.5"),
                ("claude-haiku-3-5", "Claude Haiku 3.5"),
            )
        ],
    },
    {
        "id": "openai",
        "label": "OpenAI",
        "models": [
            {
                "id": "gpt-5.4",
                "label": "GPT 5.4",
                "modes": ["api"],
                "efforts": _LEVELS,
                "defaultEffort": "medium",
            }
        ],
    },
]


def fake_models(monkeypatch: pytest.MonkeyPatch, found: list[dict[str, Any]] | None = None) -> None:
    """Hermes's model catalog for the hire checks (None = Hermes can't list them)."""
    from agos_core.actions import hire_model

    monkeypatch.setattr(
        hire_model, "catalog", lambda core, *, wait=True: CATALOG if found is None else found
    )


def hermes_webhook_routes(home: Path, put: dict[str, Any], drop: list[str]) -> None:
    """Hermes's store update of its webhook routes (its lock aside), with the same
    change AGOS runs inside it."""
    import json

    file = home / "webhook_subscriptions.json"
    routes = json.loads(file.read_text()) if file.exists() else {}
    apply_webhook_routes(routes, {"put": put, "drop": drop})
    file.write_text(json.dumps(routes))


class FakeHermes:
    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self.bodies: list[dict[str, Any]] = []
        self.messages: dict[str, list[dict[str, Any]]] = {}
        self.stopped: list[str] = []
        self.answers: list[tuple[str, str]] = []
        self.yolo: list[str] = []  # runs Hermes never asked about (Full access = YOLO)
        self.deleted: list[str] = []
        self.refuse = False
        # The fake gateway (tests/fake_gateway.py): on, and its answers in progress.
        self.gateway = True
        self.turns: dict[str, dict[str, Any]] = {}

    def create_run(self, workspace_id: str, body: dict[str, Any], *, idempotency_key: str) -> str:
        if self.refuse:
            raise EngineError("the engine refused to start the work: no credits")
        run_id = f"run_{len(self.runs) + 1}"
        self.runs[run_id] = {"status": "running"}
        self.bodies.append(body)
        return run_id

    def get_run(self, workspace_id: str, run_id: str) -> dict[str, Any] | None:
        return self.runs.get(run_id)

    def stop_run(self, workspace_id: str, run_id: str) -> None:
        self.stopped.append(run_id)
        self.runs[run_id] = {"status": "cancelled"}

    def answer_approval(self, workspace_id: str, run_id: str, choice: str) -> None:
        self.answers.append((run_id, choice))
        self.runs[run_id] = {"status": "running"}

    def steer(self, workspace_id: str, run_id: str, text: str) -> bool:
        self.steered = [*getattr(self, "steered", []), (run_id, text)]
        return True

    def delete_session(self, workspace_id: str, session_id: str) -> None:
        self.deleted.append(session_id)

    def finish(self, run_id: str, output: str) -> None:
        self.runs[run_id] = {
            "status": "completed",
            "output": output,
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            "runtime": {"provider": "anthropic", "model": "claude-sonnet-5"},
        }


Env = tuple[TestClient, FakeHermes, Any, str]


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    hermes_home = tmp_path / "home" / ".hermes"
    hermes_home.mkdir(parents=True)
    settings = Settings(
        data_dir=tmp_path / "data",
        internal_token_file=tmp_path / "data" / "system" / "internal.token",
        documents_url=None,
        engine=EngineConfig(
            hermes_bin="/bin/hermes",
            docker_bin="/bin/docker",
            hermes_home=hermes_home,
            profile_prefix="agos-",
            sandbox_image="img:1",
            host_home=tmp_path / "home",
            roots_dir=tmp_path / "data" / "hermes",
        ),
    )
    app = create_app(settings, background=False)
    with TestClient(app) as client:
        core = app.state.core
        core.engine.runner = FakeRunner(hermes_home)
        fake = FakeHermes()

        def start(workspace_id: str, **_: Any) -> None:
            if fake.refuse:  # its gateway can't start (no credits…)
                raise EngineError("the engine refused to start the work: no credits")

        core.engine.start = start
        core.engine.is_running = lambda workspace_id: True
        core.engine.stop = lambda workspace_id, **_: None
        core.engine.runs_client = fake
        core.engine.webhook_routes = lambda ws, put, drop: hermes_webhook_routes(
            core.engine.profile_home(ws), put, drop
        )
        follow_requests(client, core, fake)
        client.headers["x-agos-internal"] = settings.internal_token_file.read_text()
        ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
        yield client, fake, core, ws


def tick(core: Any) -> None:
    """One round of the workspace's Hermes gateway (a fake)."""
    pump(core, core.engine.runs_client)


def create_ws(client: TestClient, name: str) -> str:
    r = client.post("/workspaces", json={"name": name, "defaultModel": MODEL})
    return str(r.json()["id"])


def agent(client: TestClient, ws: str, name: str) -> None:
    """A team member of the workspace (one of its agents)."""
    item = client.post(
        f"/workspaces/{ws}/agents",
        json={
            "name": name,
            "title": name.title(),
            "definition": {"instructions": f"You are {name}."},
        },
    )
    assert item.status_code == 201, item.text


# What every hire must carry (actions/proposals.py check_new / decide): its whole kit
# (tools, skills, docs, onboarding; one skill from the workspace's library) and its
# whole model (an exact version of the workspace's catalog, an effort, model_why).
WHOLE_KIT: dict[str, Any] = {
    "tools": [{"name": "Google Drive", "why": "the scripts live there"}],
    "skills": [{"name": "writing", "source": "library"}],
    "docs": [{"title": "Style guide", "url": "https://example.com/style"}],
    "onboarding": {"task": "Write one hook for this week's video.", "criteria": ["short"]},
}
WHOLE_MODEL: dict[str, Any] = {
    "model": {"model": "claude-sonnet-4-5", "effort": "medium"},
    "model_why": "everyday writing -> Sonnet 4.5, medium",
}


def library_skill(core: Any, ws: str, name: str = "writing") -> None:
    """A skill in the workspace's library (a hire's kit needs one it has)."""
    from agos_core.actions import workspace_skills
    from agos_core.engine import library as lib

    workspace_skills.create(
        core,
        ws,
        name,
        title=name.title(),
        given={"text": lib.skill_template(name, f"Use when doing {name}.", f"# {name}")},
    )


def whole(hire: dict[str, Any], **more: Any) -> dict[str, Any]:
    """A hire with the kit and model every hire needs (its own fields win)."""
    return {"kit": WHOLE_KIT, **WHOLE_MODEL, **hire, **more}


def kanban_of(core: Any, ws: str) -> dict[str, dict[str, Any]]:
    """The workspace's Kanban cards in the fake Hermes (FakeRunner)."""
    cards: dict[str, dict[str, Any]] = core.engine.runner.kanban.setdefault(
        core.engine.profile(ws), {}
    )
    return cards


@pytest.fixture
def fake_board(monkeypatch: pytest.MonkeyPatch) -> None:
    """AGOS reads the cards' status from the board's database; here, from the fake."""
    from agos_core.actions import kanban_board

    def facts(core: Any, ws: str, ids: list[str]) -> dict[str, dict[str, str]]:
        cards = kanban_of(core, ws)
        return {
            c: {
                "status": str(cards[c]["status"]),
                "title": str(cards[c]["title"]),
                "result": str(cards[c].get("result") or ""),
            }
            for c in ids
            if c in cards
        }

    monkeypatch.setattr(kanban_board, "facts", facts)

    def keyed(core: Any, ws: str, prefix: str) -> list[dict[str, Any]]:
        return [
            {
                "id": c["id"],
                "status": str(c["status"]),
                "title": str(c["title"]),
                "result": str(c.get("result") or ""),
                "key": str(c["key"]),
                "created_at": c.get("created_at"),
                "completed_at": c.get("completed_at"),
                "parents": list(c.get("parents") or []),
            }
            for c in kanban_of(core, ws).values()
            if str(c.get("key") or "").startswith(prefix)
        ]

    monkeypatch.setattr(kanban_board, "keyed", keyed)
