"""Settings → Tools: the GitHub token Hermes's Skills Hub reads.

Runs the real Hermes (its save_env_value / remove_env_value / GitHubAuth) on two
throwaway homes: the token lands in the shared home and the library's home only,
GitHub's refusal removes it again, and General Settings never copies it into a
workspace.
"""

import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from agos_core.actions import general_sync
from agos_core.config import EngineConfig
from agos_core.engine import github_token as gt
from agos_core.engine.github_token import GithubToken, TokenProblem, TokenStatus, clean_token


def _engine(tmp_path: Path) -> EngineConfig | None:
    hermes = shutil.which("hermes")
    if not hermes:
        return None
    tools = Path.home() / ".hermes" / "tools"
    return EngineConfig(
        hermes_bin=hermes,
        docker_bin="docker",
        hermes_home=tmp_path / "shared",
        profile_prefix="agos-",
        sandbox_image="x",
        host_home=Path.home(),
        roots_dir=tmp_path / "roots",
        runtime_dir=tools if tools.is_dir() else None,
    )


def _env(home: Path) -> str:
    path = home / ".env"
    return path.read_text() if path.is_file() else ""


def test_token_shape_is_checked() -> None:
    assert clean_token("  github_pat_AB12_cd  ") == "github_pat_AB12_cd"
    for bad in ("", "a b", "x" * 401, "tok;rm"):
        with pytest.raises(TokenProblem):
            clean_token(bad)


def test_hermes_saves_it_in_both_homes_and_removes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _engine(tmp_path)
    if engine is None:
        pytest.skip("no Hermes install on this machine")
    library = tmp_path / "library"
    token = GithubToken(engine, library)
    # GitHub's answer is the network's business; here it accepts the token.
    accepted = TokenStatus(True, "pat", 5000, 4999, None, False, None)
    monkeypatch.setattr(token, "status", lambda: accepted)
    token.save("github_pat_TEST_only_123")
    for home in (engine.hermes_home, library):
        assert "GITHUB_TOKEN=github_pat_TEST_only_123" in _env(home), home
        assert oct((home / ".env").stat().st_mode & 0o777) == "0o600"
    token.remove()
    for home in (engine.hermes_home, library):
        assert "GITHUB_TOKEN" not in _env(home)


def test_a_refused_token_is_taken_back_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(tmp_path)
    if engine is None:
        pytest.skip("no Hermes install on this machine")
    library = tmp_path / "library"
    token = GithubToken(engine, library)
    refused = TokenStatus(True, "pat", None, None, None, True, None)
    monkeypatch.setattr(token, "status", lambda: refused)
    with pytest.raises(TokenProblem, match="refused"):
        token.save("github_pat_WRONG_123")
    for home in (engine.hermes_home, library):
        assert "GITHUB_TOKEN" not in _env(home)


@pytest.mark.skipif(os.environ.get("AGOS_NETWORK_TESTS") != "1", reason="reaches GitHub")
def test_status_comes_from_hermess_own_github_auth(tmp_path: Path) -> None:
    """The real GitHubAuth against GitHub: no token = anonymous at 60/hour; a fake
    token = GitHub's 401, so save() refuses and removes it."""
    engine = _engine(tmp_path)
    if engine is None:
        pytest.skip("no Hermes install on this machine")
    library = tmp_path / "library"
    token = GithubToken(engine, library)
    status = token.status()
    assert status.saved is False
    if status.method == "anonymous":
        assert status.limit == 60 or status.error
    with pytest.raises(TokenProblem):
        token.save("github_pat_" + "0" * 40)
    assert "GITHUB_TOKEN" not in _env(library)


def test_status_script_output_is_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    token = GithubToken(cast(Any, SimpleNamespace()), tmp_path)
    answer = {
        "saved": True,
        "method": "pat",
        "limit": 5000,
        "remaining": 12,
        "reset": 1792180000,
        "rejected": False,
        "error": None,
    }
    monkeypatch.setattr(token, "_run", lambda *a, **k: json.dumps(answer))
    status = token.status()
    assert (status.saved, status.method, status.limit, status.remaining) == (True, "pat", 5000, 12)


def test_general_settings_never_copy_it_into_workspaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import agos_core.db.app_settings as app_settings

    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / ".env").write_text("OPENROUTER_API_KEY=sk-or\nGITHUB_TOKEN=github_pat_x\n")
    core = cast(
        Any,
        SimpleNamespace(
            db=None,
            engine=SimpleNamespace(settings=SimpleNamespace(hermes_home=shared)),
        ),
    )
    # Even when it was once saved as a key name, it stays out.
    monkeypatch.setattr(app_settings, "get_setting", lambda *_a, **_k: ["GITHUB_TOKEN"])
    names = general_sync.managed_names(core)
    assert "OPENROUTER_API_KEY" in names
    assert "GITHUB_TOKEN" not in names
    assert gt.NAME == "GITHUB_TOKEN"
