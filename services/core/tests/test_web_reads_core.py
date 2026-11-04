"""The web reads what the core (or Hermes) knows instead of repeating it (STEP27
audit, area 2 (c)): Hermes's provider names, a tool service's sign-in, Hermes's
defaults, its job states and schedule words, its Kanban columns, the core's
attachment limits and trash window. The last test greps the web so none of the
old copies comes back."""

import ast
import re
from pathlib import Path
from typing import Any

import pytest
from test_library import env, ws  # noqa: F401 - fixture

from agos_core.actions import kanban_board, ongoing
from agos_core.api.models import CatalogProvider
from agos_core.engine import cron, hermes_tools, provider_login

REPO = Path(__file__).resolve().parents[3]
WEB = REPO / "apps" / "web" / "src"
HERMES = Path.home() / ".hermes" / "hermes-agent"


def test_the_catalog_says_hermes_s_provider_name_for_each_way_in() -> None:
    def provider(pid: str, modes: list[str]) -> dict[str, Any]:
        model = {"id": "m", "label": "m", "modes": modes, "efforts": [], "defaultEffort": ""}
        return CatalogProvider.model_validate(
            {"id": pid, "label": pid, "models": [model]}
        ).model_dump(by_alias=True)

    assert provider("openai", ["cli", "api"])["hermesProviders"] == {
        "cli": "openai-codex",
        "api": "openai-api",
    }
    assert provider("claude", ["cli"])["hermesProviders"] == {"cli": "anthropic"}
    assert provider("openrouter", ["api"])["hermesProviders"] == {"api": "openrouter"}


def test_a_tool_service_s_sign_in_comes_from_the_core() -> None:
    assert provider_login.sign_in_for({"login": "xai_grok"}) == {
        "id": "xai",
        "label": "Sign in to xAI (Grok)",
    }
    assert provider_login.sign_in_for({"nous": True})["id"] == "nous"  # type: ignore[index]
    # A sign-in Hermes adds that AGOS can't start: said, not dropped.
    found = provider_login.sign_in_for({"login": "new_login", "login_is_auth": True})
    assert found is not None and found["id"] is None and "new_login" in str(found["label"])
    # An install step is not a sign-in.
    assert provider_login.sign_in_for({"login": "camofox"}) is None
    before = dict(hermes_tools._current)
    hermes_tools._current["list"] = [
        {"key": "x_search", "providers": [{"name": "xAI", "login": "xai_grok", "env": []}]}
    ]
    try:
        assert hermes_tools.providers("x_search")[0]["signIn"]["id"] == "xai"
    finally:
        hermes_tools._current.clear()
        hermes_tools._current.update(before)


def test_the_board_s_buttons_follow_hermes_s_manual_moves() -> None:
    manual = kanban_board._manual(None)  # v0.22.2's table
    acts = {s: kanban_board.card_actions(s, manual) for s in kanban_board.STATUSES}
    # Hermes refuses complete/block on triage/todo/scheduled (kanban_db.py
    # complete_task / block_task gates): no Done / Stop there.
    for s in ("triage", "todo", "scheduled"):
        assert acts[s] == ["archive"], s
    for s in ("ready", "running"):
        assert acts[s] == ["done", "block", "archive"], s
    assert acts["blocked"] == ["unblock", "done", "archive"]
    assert acts["review"] == ["done", "archive"]
    assert acts["done"] == ["archive"]
    assert acts["archived"] == []
    # Hermes's table wins over the fallback when it is read.
    read = kanban_board._manual({"manual": {"todo": ["done"]}})
    assert kanban_board.card_actions("todo", read) == ["done", "archive"]
    assert kanban_board.card_actions("ready", read) == ["archive"]


@pytest.mark.skipif(
    not (HERMES / "hermes_cli" / "kanban_workflow.py").is_file(), reason="no Hermes"
)
def test_the_fallback_moves_are_the_installed_hermes_s() -> None:
    import runpy

    # kanban_workflow.py is pure data + stdlib (its own docstring).
    found = runpy.run_path(str(HERMES / "hermes_cli" / "kanban_workflow.py"))
    manual = found["DEFAULT_WORKFLOW"].to_dict()["manual"]
    assert {k: tuple(v) for k, v in manual.items()} == kanban_board.MANUAL


@pytest.mark.skipif(
    not (HERMES / "hermes_cli" / "kanban_workflow.py").is_file(), reason="no Hermes"
)
def test_the_fallback_columns_are_the_installed_hermes_s() -> None:
    tree = ast.parse((HERMES / "hermes_cli" / "kanban_workflow.py").read_text())
    keys = [
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "Column"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ]
    assert [*keys, "archived"] == list(kanban_board.STATUSES)


def test_job_state_and_schedule_words_are_hermes_s(tmp_path: Path) -> None:
    job = {
        "id": "j1",
        "enabled": False,
        "state": "completed",
        "schedule": {"kind": "interval", "minutes": 30, "display": "every 30m"},
        "schedule_display": "every 30m",
        "paused_reason": None,
    }
    shown = ongoing._view(job)
    assert shown.state == "completed" and shown.schedule == "every 30m"
    state = cron.job_state(tmp_path, job)
    assert state["state"] == "completed" and state["schedule_display"] == "every 30m"
    # No state written by Hermes yet: on/off as Hermes keeps it.
    assert ongoing._view({"id": "j2", "enabled": False}).state == "paused"


def test_the_core_says_its_limits(env: Any) -> None:  # noqa: F811
    from agos_core.background.trash import TRASH_DAYS
    from agos_core.engine import attachments

    client, _core, _runner, _home = env
    facts = client.get("/app/facts").json()
    assert facts["trashDays"] == TRASH_DAYS
    assert facts["attachments"]["maxFiles"] == attachments.MAX_FILES
    assert facts["attachments"]["maxFileBytes"] == attachments.MAX_FILE_BYTES
    assert facts["attachments"]["maxTotalBytes"] == attachments.MAX_TOTAL_BYTES
    assert set(facts["attachments"]["imageTypes"]) == attachments.IMAGE_TYPES
    assert facts["attachments"]["maxVoiceSeconds"] == attachments.MAX_VOICE_SECONDS


def test_the_board_has_hermes_s_columns_and_each_card_its_buttons(env: Any) -> None:  # noqa: F811
    client, _core, _runner, _home = env
    a = ws(client, "Alpha")
    board = client.get(f"/workspaces/{a}/kanban").json()
    assert [c["status"] for c in board["columns"]] == list(kanban_board.STATUSES)
    # The Office's open cards: the core says which columns still have work ahead.
    assert [c["status"] for c in board["columns"] if not c["open"]] == ["done", "archived"]
    # The Ready hint's round: Hermes's dispatch interval as the gateway reads it.
    _core.engine.unmanaged_hermes(a, "config", "set", kanban_board.DISPATCH_KEY, "45")
    assert client.get(f"/workspaces/{a}/kanban").json()["dispatchSeconds"] == 45


# The copies the web used to keep, each with where it now comes from.
GONE = {
    r"claude-opus-5-5": "new workspace: Hermes's model or the catalog's first",
    r"\"openai-codex\"|\"openai-api\"": "Hermes provider names: catalog hermesProviders",
    r"xai_grok|openai_codex": "a tool service's sign-in: the core's signIn",
    r"\?\? \"20\"|default is 20": "goals.max_turns: Hermes's default from its schema",
    r"Video & pictures": "the old video group: Settings → Helper models (Hermes's own tasks)",
    r"placeholder=\"openrouter\"|google/gemini-2\.5-flash": "a helper model: Hermes's value",
    r"Custom schedule": "a schedule's words: Hermes's schedule_display",
    r"\? \"Paused\" : \"Done\"": "a job's state: Hermes's state",
    r"MAX_FILE_BYTES =|MAX_TOTAL_BYTES =|MAX_FILES =": "attachment limits: /app/facts",
    r"TRASH_DAYS": "the trash window: /app/facts",
    r"after 30 minutes": "the screen's idle stop: Hermes's bot_desktop.idle_stop_minutes",
    r"modes\[0\] \?\? \"cli\"": "a starting model: features/models/first-choice.ts (one helper)",
    r"MAX_RECORDING_SECONDS|10 \* 60": "a voice note's length: /app/facts maxVoiceSeconds",
    r"grid-cols-9|\[\"triage\", \"todo\"": "Kanban columns and buttons: the board's columns/actions",
    r"about a minute": "the dispatcher's round: the board's dispatchSeconds (Hermes's)",
    r"\"running\",\s*\"blocked\",\s*\"review\"": "the Office's open cards: the board's column open",
    r"for 30 days": "the trash window: /app/facts trashDays",
}


def test_the_web_keeps_none_of_the_old_copies() -> None:
    found: list[str] = []
    for path in WEB.rglob("*.ts*"):
        if path.name.endswith(".d.ts"):
            continue
        text = path.read_text()
        for pattern, why in GONE.items():
            if re.search(pattern, text):
                found.append(f"{path.relative_to(WEB)}: /{pattern}/ ({why})")
    assert not found, found
