"""Step 38 B: Library → tools and Settings → Tools → GitHub token ask Hermes once
and then not again while what Hermes reads holds (engine/read_cache.py), and the
read-ahead after start fills both."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from test_library import env, ws  # noqa: F401 - fixture

from agos_core.engine import read_ahead
from agos_core.engine.read_cache import ReadCache


def test_tool_services_are_kept_on_what_hermes_reads(tmp_path: Path) -> None:
    """Hermes's picker reads the home's config.yaml, .env and auth.json and, through
    its .env load, the managed scope: kept while what they hold is the same (a
    rewrite with the same text included), asked again when one changes."""
    from agos_core.engine import hermes as engine_mod

    managed = tmp_path / "managed"
    managed.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text("web:\n  backend: ddgs\n")
    runs: list[Path] = []

    def now(h: Path) -> dict[str, str | None]:
        runs.append(h)
        return {"web": "ddgs"}

    engine = SimpleNamespace(
        settings=SimpleNamespace(managed_home=managed),
        _services=ReadCache("test-tool-services"),
        _tool_services_now=now,
    )
    asked = engine_mod.HermesEngine.tool_services_in
    assert asked(engine, home) == {"web": "ddgs"}  # type: ignore[arg-type]
    time.sleep(0.01)
    (home / "config.yaml").write_text("web:\n  backend: ddgs\n")  # same text
    asked(engine, home)  # type: ignore[arg-type]
    assert len(runs) == 1
    (managed / ".env").write_text("FIRECRAWL_API_KEY=x\n")  # the managed scope
    asked(engine, home)  # type: ignore[arg-type]
    assert len(runs) == 2
    (home / "auth.json").write_text("{}")
    asked(engine, home)  # type: ignore[arg-type]
    assert len(runs) == 3


def _token_status(monkeypatch: Any) -> list[str]:
    from agos_core.engine import github_token as gt

    calls: list[str] = []
    state = gt.TokenStatus(True, "pat", 5000, 4990, 1792180000, False, None)

    def status(self: Any) -> Any:
        calls.append(str(self.library_home))
        return state

    monkeypatch.setattr(gt.GithubToken, "status", status)
    return calls


def test_the_github_token_state_is_asked_once_while_the_env_files_hold(
    env: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    """Hermes's GitHub auth (the token in its .env) and GitHub's hourly numbers: the
    page gets the last answer at once (the numbers asked again behind it every
    minute); a new token (the .env changes) is asked for before the page shows."""
    from agos_core.actions import library

    client, core, _runner, _home = env
    calls = _token_status(monkeypatch)
    assert client.get("/library/github-token").status_code == 200
    assert client.get("/library/github-token").json()["remaining"] == 4990
    assert len(calls) == 1
    home = library.library_home(core)
    home.mkdir(parents=True, exist_ok=True)
    (home / ".env").write_text("GITHUB_TOKEN=github_pat_x\n")
    assert client.get("/library/github-token").status_code == 200
    assert len(calls) == 2


def test_the_read_ahead_fills_the_library_and_the_token_state(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    ws(client, "Alpha")
    runs: list[str] = []

    def services(home: Any) -> dict[str, Any]:
        runs.append(str(home))
        return {}

    core.engine.tool_services_in = services
    calls = _token_status(monkeypatch)
    assert "agos_core.actions.library:read_ahead" in read_ahead.WARMERS
    read_ahead.run(core, ("agos_core.actions.library:read_ahead",))
    assert runs and calls
    assert ReadCache.settle(10)
    seen = (len(runs), len(calls))
    assert client.get("/library/github-token").status_code == 200
    assert len(calls) == seen[1]
