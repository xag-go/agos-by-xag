"""Settings → Errors (actions/error_issues.py, error_alerts.py, hermes_errors.py,
api/errors.py, the catch-all handler in api/app.py)."""

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import test_api
from fastapi import APIRouter
from fastapi.testclient import TestClient

from agos_core.actions import error_alerts, error_issues, hermes_errors
from agos_core.api.app import create_app
from agos_core.config import Settings
from agos_core.db.connection import open_database

client = test_api.client  # the API tests' fixture


def core_of(client: TestClient) -> Any:
    return client.app.state.core  # type: ignore[attr-defined]


def _db() -> Any:
    return open_database(":memory:")


def _boom(n: int) -> None:
    raise KeyError(f"card {n} at /srv/agos/x/y.json")


def test_one_issue_per_fingerprint_with_count_first_last_and_version() -> None:
    db = _db()
    seen: list[tuple[int, str | None]] = []
    for n in range(3):
        try:
            _boom(n)
        except KeyError as error:
            seen.append(
                error_issues.record(
                    db,
                    source="core",
                    where="agos.test",
                    error_type="KeyError",
                    message=f"lost {n} — {error}",
                    frames=error_issues.frames_of(error.__traceback__),
                )
            )
    assert [alert for _, alert in seen] == ["new", None, None]
    assert len({issue for issue, _ in seen}) == 1
    [issue] = error_issues.listed(db)
    assert issue.count == 3 and issue.first_seen <= issue.last_seen
    assert issue.version == error_issues.agos_version() and issue.version != ""
    # Another message shape, or the same in another workspace, is another issue.
    error_issues.record(
        db, source="core", where="x", error_type="KeyError", message="other", frames=[]
    )
    assert len(error_issues.listed(db)) == 2
    assert error_issues.normalize("card 12 at /a/b/c id 0xdeadbeef 'x'") == (
        "card <n> at <path> id <hex> <v>"
    )


def test_marked_fixed_it_comes_back_and_a_spike_is_told_once() -> None:
    db = _db()
    kw: dict[str, Any] = {
        "source": "web",
        "where": "web page",
        "error_type": "TypeError",
        "message": "x is undefined",
        "frames": ["Page"],
    }
    issue, alert = error_issues.record(db, **kw)
    assert alert == "new"
    assert error_issues.set_status(db, issue, "fixed", workspace_id=None) == "open"
    assert error_issues.listed(db) == [] and len(error_issues.listed(db, status="fixed")) == 1
    _, alert = error_issues.record(db, **kw)
    assert alert == "back"
    [back] = error_issues.listed(db)
    assert back.status == "open" and back.came_back
    at = datetime(2026, 11, 2, 10, 5, tzinfo=UTC)
    alerts = [error_issues.record(db, **kw, at=at + timedelta(seconds=i))[1] for i in range(40)]
    assert alerts.count("spike") == 1
    with pytest.raises(Exception, match="no such error"):
        error_issues.set_status(db, 999, "fixed", workspace_id=None)


def test_an_unhandled_route_error_is_a_typed_500_logged_and_grouped(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        internal_token_file=tmp_path / "data" / "system" / "internal.token",
        documents_url=None,
    )
    app = create_app(settings, background=False)
    broken = APIRouter()

    @broken.get("/workspaces/{workspace_id}/broken")
    def explode(workspace_id: str) -> None:
        raise RuntimeError(f"exploded with token=sk-abcdefghijklmnopqrstu in {workspace_id}")

    app.include_router(broken)
    with TestClient(app, raise_server_exceptions=False) as client:
        client.headers["x-agos-internal"] = settings.internal_token_file.read_text()
        ws = test_api.create_workspace(client, "Errors WS")
        answer = client.get(f"/workspaces/{ws}/broken")
        assert answer.status_code == 500
        body = answer.json()
        assert body["code"] == "internal_error" and len(body["requestId"]) == 12
        assert body["requestId"] in body["detail"]
        client.get(f"/workspaces/{ws}/broken")
        [issue] = client.get("/errors").json()["issues"]
        assert issue["count"] == 2 and issue["source"] == "core"
        assert issue["workspaceId"] == ws and issue["errorType"] == "RuntimeError"
        assert issue["route"] == "GET /workspaces/{workspace_id}/broken"
        assert "explode" in issue["trace"] and "sk-abcdefghijklmnop" not in issue["trace"]
        assert "sk-abcdefghijklmnop" not in issue["message"]
        rows = (
            core_of(client)
            .db.execute("SELECT workspace_id, text FROM system_log WHERE level = 'error'")
            .fetchall()
        )
        assert any(r["workspace_id"] == ws and body["requestId"] in r["text"] for r in rows)
        # Filters, Mark fixed and open again.
        assert client.get("/errors", params={"source": "web"}).json()["issues"] == []
        assert client.get("/errors", params={"workspace": "-"}).json()["issues"] == []
        assert client.post(f"/errors/{issue['id']}/fixed").json() == {"before": "open"}
        assert client.get("/errors").json()["issues"] == []
        assert client.post(f"/errors/{issue['id']}/open").json() == {"before": "fixed"}


def test_agos_core_loggers_reach_the_system_log_and_zero_workspaces_work(
    client: TestClient,
) -> None:
    logging.getLogger("agos_core.engine.read_cache").error("read failed for card 7")
    db = core_of(client).db
    assert (
        db.execute(
            "SELECT count(*) FROM system_log WHERE source = 'agos_core.engine.read_cache'"
        ).fetchone()[0]
        == 1
    )
    [issue] = client.get("/errors").json()["issues"]
    assert issue["workspaceId"] is None and issue["where"] == "agos_core.engine.read_cache"
    assert client.get("/errors").json()["version"]


def test_the_web_reports_a_page_error_rate_limited(client: TestClient, monkeypatch: Any) -> None:
    from agos_core.api import errors as errors_api

    monkeypatch.setattr(errors_api, "_reports", [])
    report = {
        "kind": "page",
        "name": "TypeError",
        "message": "Cannot read properties of undefined (reading 'title') token=abcdef1234567",
        "stack": "TypeError: x\n    at CardModal (webpack://app/card.tsx:10:5)\n    at div",
        "digest": "12345",
        "url": "/settings/errors?x=1",
    }
    assert client.post("/errors/report", json=report).status_code == 204
    [issue] = client.get("/errors", params={"source": "web"}).json()["issues"]
    assert issue["errorType"] == "TypeError" and issue["route"] == "/settings/errors"
    assert "abcdef1234567" not in issue["message"]
    for _ in range(errors_api.REPORTS_PER_MINUTE + 5):
        client.post("/errors/report", json=report)
    [issue] = client.get("/errors", params={"source": "web"}).json()["issues"]
    assert issue["count"] == errors_api.REPORTS_PER_MINUTE


def test_alerts_follow_the_notifications_setting(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agos_core.actions import outbox_push
    from agos_core.actions.notification_rules import EVENTS, save_notifications
    from agos_core.actions.services.channel import owner_needs

    assert EVENTS["agos.error"][1] == "instant"
    core = core_of(client)
    told: list[tuple[str, str]] = []
    pushed: list[str] = []

    def tell_owner(c: Any, w: str, t: str, chat_id: int | None = None) -> int:
        told.append((w, t))
        return 1

    def push(*args: Any, **_: Any) -> int:
        pushed.append(str(args[2]))
        return 1

    monkeypatch.setattr(owner_needs, "tell_owner", tell_owner)
    monkeypatch.setattr(owner_needs, "push", push)
    monkeypatch.setattr(outbox_push, "queue", push)
    issue, _ = error_issues.record(
        core.db, source="core", where="agos.x", error_type="OSError", message="disk", frames=[]
    )
    # No workspace yet: the installed app only (queued on the outbox).
    assert error_alerts.tell(core, issue, "new") and told == [] and len(pushed) == 1
    assert "new error" in pushed[0] and "Settings → Errors" in pushed[0]
    ws = test_api.create_workspace(client, "Alerts WS")
    assert error_alerts.tell(core, issue, "back")
    assert told[-1][0] == ws and "came back" in told[-1][1] and len(pushed) == 2
    save_notifications(core, {"agos.error": "silent"})
    assert not error_alerts.tell(core, issue, "spike") and len(pushed) == 2
    save_notifications(core, {"agos.error": "batched"})
    from agos_core.actions import digest

    monkeypatch.setattr(digest, "keep_job_soon", lambda c, w: None)
    assert error_alerts.tell(core, issue, "spike") and len(pushed) == 2
    assert "happening a lot" in str(digest.take(core, ws))


def test_the_alerts_thread_caps_an_hour_and_ignores_its_own_errors(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = core_of(client)
    sent: list[int] = []

    def tell(_core: Any, issue: int, _kind: str) -> bool:
        sent.append(issue)
        return True

    monkeypatch.setattr(error_alerts, "tell", tell)
    alerts = error_alerts.Alerts(core)
    for n in range(error_alerts.PER_HOUR + 5):
        alerts(n, "new")
    alerts.stop()
    assert sent == list(range(error_alerts.PER_HOUR))


HERMES_ERRORS = """--- ~/.hermes/logs/errors.log [level>=ERROR] (last 500) ---
2026-11-02 10:00:00,100 ERROR [20261102_x] gateway.platforms.telegram: send failed for chat 123
Traceback (most recent call last):
  File "/h/gateway/run.py", line 10, in send
telegram.error.NetworkError: timed out
2026-11-02 10:01:00,000 WARNING agent.tools: not ours
2026-11-02 10:02:00,200 ERROR gateway.run: send failed for chat 456
"""


def test_hermes_errors_are_parsed_and_counted_once_per_entry(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    found = hermes_errors.entries(HERMES_ERRORS)
    assert [(e["logger"], e["type"]) for e in found] == [
        ("gateway.platforms.telegram", "NetworkError"),
        ("gateway.run", ""),
    ]
    assert "NetworkError" in found[0]["trace"]
    core = core_of(client)
    ws = test_api.create_workspace(client, "Hermes WS")
    home = tmp_path / "root"
    (home / "logs").mkdir(parents=True)
    log_file = home / "logs" / "errors.log"
    log_file.write_text("x")
    calls: list[str] = []

    class FakeEngine:
        def profile_home(self, _ws: str) -> Path:
            return home

        def hermes_check(self, w: str, what: str, timeout: float = 0) -> tuple[str, int]:
            calls.append(what)
            return HERMES_ERRORS, 0

    core = SimpleNamespace(db=core.db, engine=FakeEngine(), settings=core.settings)
    alerted: list[int] = []
    handler = next(h for h in logging.getLogger("agos").handlers if hasattr(h, "alert"))
    monkeypatch.setattr(handler, "alert", lambda i, k: alerted.append(i))
    assert hermes_errors.read(core, ws) == 2
    assert alerted == []  # the first look is old news
    assert hermes_errors.read(core, ws) == 0 and calls == ["errors"]  # file unchanged
    log_file.write_text("xy")
    assert hermes_errors.read(core, ws) == 0  # nothing newer than what was counted
    issues = client.get("/errors", params={"source": "hermes", "workspace": ws}).json()["issues"]
    assert {i["where"] for i in issues} == {"gateway.platforms.telegram", "gateway.run"}
    assert all(i["count"] == 1 for i in issues)
    # Hermes's lines are not copied into the workspace Log (it reads Hermes's logs).
    assert (
        core.db.execute(
            "SELECT count(*) FROM system_log WHERE source = 'agos.hermes_errors'"
        ).fetchone()[0]
        == 0
    )


def test_the_alerts_place_label_never_names_the_engine(client: TestClient) -> None:
    """Spec 2026-11-04 (no engine name): the alert the owner reads says "the engine",
    never "Hermes"; the `source` field itself stays as it is (diagnostics)."""
    core = core_of(client)
    issue_id, _ = error_issues.record(
        core.db, source="hermes", where="gateway", error_type="E", message="m", frames=[]
    )
    issue = error_issues.get(core.db, issue_id)
    assert issue is not None and issue.source == "hermes"
    for source in error_issues.SOURCES:
        said = error_alerts._where(core, issue.model_copy(update={"source": source}))
        assert "Hermes" not in said
    text = error_alerts.text_for(issue, "new", error_alerts._where(core, issue))
    assert "the engine" in text and "Hermes" not in text


def test_the_cofounder_marks_an_error_fixed_with_undo(client: TestClient) -> None:
    from agos_core.actions import cofounder_more

    core = core_of(client)
    ws = test_api.create_workspace(client, "CF WS")
    other = test_api.create_workspace(client, "Other WS")
    mine, _ = error_issues.record(
        core.db, source="core", where="a", error_type="E", message="m", frames=[], workspace_id=ws
    )
    theirs, _ = error_issues.record(
        core.db,
        source="core",
        where="a",
        error_type="E",
        message="m",
        frames=[],
        workspace_id=other,
    )
    result = cofounder_more.do(core, ws, "mark_error_fixed", {"error": mine})
    assert error_issues.get(core.db, mine).status == "fixed"  # type: ignore[union-attr]
    cofounder_more.undo(core, ws, "mark_error_fixed", result)
    assert error_issues.get(core.db, mine).status == "open"  # type: ignore[union-attr]
    with pytest.raises(Exception, match="no such error"):
        cofounder_more.do(core, ws, "mark_error_fixed", {"error": theirs})


def test_the_deadman_place_names_the_bot_env_never_the_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from agos_core.actions import deadman, hermes_channel, telegram_people

    core = core_of(client)
    assert deadman.write_place(core) is False
    ws = test_api.create_workspace(client, "Bot WS")
    home = tmp_path / "root"

    class FakeEngine:
        def profile_home(self, _ws: str) -> Path:
            return home

    core = SimpleNamespace(db=core.db, engine=FakeEngine(), settings=core.settings)
    monkeypatch.setattr(
        hermes_channel, "bot_token", lambda c, w: "123456:AAsecret" if w == ws else ""
    )
    monkeypatch.setattr(telegram_people, "owner_id", lambda c, w: "777")
    assert deadman.write_place(core) is True
    path = core.settings.data_dir / "system" / deadman.FILE
    shown = json.loads(path.read_text())
    assert shown == {"envFile": str(home / ".env"), "chatId": "777", "workspace": "Bot WS"}
    assert "AAsecret" not in path.read_text() and path.stat().st_mode & 0o077 == 0


def test_a_background_loop_that_dies_is_an_error_issue(client: TestClient) -> None:
    import asyncio

    from agos_core.actions.services.system.startup import loop_ended as _loop_ended

    async def run_forever() -> None:
        raise OSError("disk full")

    async def main() -> None:
        task = asyncio.create_task(run_forever())
        with pytest.raises(OSError):
            await task
        _loop_ended(task)

    asyncio.run(main())
    [issue] = client.get("/errors").json()["issues"]
    assert issue["errorType"] == "OSError" and "test_error_issues.run_forever" in issue["message"]


def test_a_value_wiped_already_is_not_wiped_twice() -> None:
    from agos_core.actions.system_log import redact

    assert redact("token=[hidden] and token=abcdef1234") == "token=[hidden] and token=[hidden]"


def test_the_version_names_the_checkouts_commit_without_a_git_process(tmp_path: Path) -> None:
    import subprocess

    repo = error_issues._REPO
    sha = subprocess.run(  # noqa: S603 - fixed argv
        ["git", "-C", str(repo), "rev-parse", "HEAD"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if sha:  # a release tarball has no .git
        assert error_issues._head_sha(repo) == sha
    # A worktree's .git file, a symbolic ref and packed refs.
    common = tmp_path / "main.git"
    (common / "worktrees" / "w").mkdir(parents=True)
    (common / "packed-refs").write_text("# pack\n" + "a" * 40 + " refs/heads/x\n")
    (common / "worktrees" / "w" / "HEAD").write_text("ref: refs/heads/x\n")
    (common / "worktrees" / "w" / "commondir").write_text("../..\n")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {common / 'worktrees' / 'w'}\n")
    assert error_issues._head_sha(wt) == "a" * 40
    (common / "worktrees" / "w" / "HEAD").write_text("b" * 40 + "\n")
    assert error_issues._head_sha(wt) == "b" * 40
    assert error_issues._head_sha(tmp_path / "nothing") == ""


def test_hermes_down_or_slow_is_a_typed_503_not_an_internal_error(tmp_path: Path) -> None:
    from agos_core.hermes_gateway import HermesTimeout, HermesUnavailable

    settings = Settings(
        data_dir=tmp_path / "data",
        internal_token_file=tmp_path / "data" / "system" / "internal.token",
        documents_url=None,
    )
    app = create_app(settings, background=False)
    broken = APIRouter()

    @broken.get("/workspaces/{workspace_id}/down")
    def down(workspace_id: str) -> None:
        raise HermesUnavailable(f"/roots/agos-{workspace_id}")

    @broken.get("/workspaces/{workspace_id}/slow")
    def slow(workspace_id: str) -> None:
        raise HermesTimeout("Hermes didn't answer in time.", started=True)

    app.include_router(broken)
    with TestClient(app, raise_server_exceptions=False) as client:
        client.headers["x-agos-internal"] = settings.internal_token_file.read_text()
        ws = test_api.create_workspace(client, "Hermes down WS")
        for path, code, detail in (
            ("down", "HERMES_UNAVAILABLE", "Hermes isn't answering right now"),
            ("slow", "HERMES_TIMEOUT", "Hermes didn't answer in time."),
        ):
            answer = client.get(f"/workspaces/{ws}/{path}")
            assert answer.status_code == 503, path
            assert answer.headers["retry-after"] == "30"
            body = answer.json()
            assert set(body) == {"detail", "code", "help", "requestId"}
            assert body["code"] == code and len(body["requestId"]) == 12
            assert body["detail"].startswith(detail)
            assert "/roots/" not in body["detail"]  # the root stays in the log
        # Hermes being down is not an AGOS bug: no issue in Settings → Errors.
        assert client.get("/errors").json()["issues"] == []


def test_an_undo_never_reopens_another_workspaces_error(client: TestClient) -> None:
    """The Undo's result names an error id: it is scoped like the action itself (an
    error of this workspace or of AGOS itself), never another workspace's."""
    from agos_core.actions import cofounder_more

    core = core_of(client)
    ws = test_api.create_workspace(client, "Undo WS")
    other = test_api.create_workspace(client, "Other undo WS")
    theirs, _ = error_issues.record(
        core.db,
        source="core",
        where="b",
        error_type="E",
        message="m",
        frames=[],
        workspace_id=other,
    )
    core.db.execute("UPDATE error_issues SET status = 'fixed' WHERE id = ?", (theirs,))
    with pytest.raises(Exception, match="no such error"):
        cofounder_more.undo(core, ws, "mark_error_fixed", {"error": theirs, "before": "open"})
    assert error_issues.get(core.db, theirs).status == "fixed"  # type: ignore[union-attr]
    # The owner's Settings → Errors page marks any of them (every workspace's).
    assert client.post(f"/errors/{theirs}/open").json()["before"] == "fixed"
