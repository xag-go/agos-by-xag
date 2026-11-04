"""M2 / P7 (925047d area 1): a root's sign-in state, its model's provider and its
credential pool are read by Hermes's own functions (engine.hermes_logins: load_config,
PROVIDER_REGISTRY, read_credential_pool, is_borrowed_credential_source,
get_auth_status), run against the installed Hermes in throwaway homes (HOME too:
nothing of the machine's own logins is read). Skipped without Hermes."""

import json
import shutil
from pathlib import Path

import pytest

from agos_core.actions import general_sync
from agos_core.config import EngineConfig
from agos_core.engine.hermes import HermesEngine


@pytest.fixture(scope="module")
def scratch_home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One throwaway HOME for the module (Hermes prepares its runtime once there)."""
    return tmp_path_factory.mktemp("home")


@pytest.fixture
def engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scratch_home: Path) -> HermesEngine:
    monkeypatch.undo()  # the real Hermes, not conftest's stand-in
    hermes = shutil.which("hermes")
    if not hermes:
        pytest.skip("no Hermes install on this machine")
    tools = Path.home() / ".hermes" / "tools"
    return HermesEngine(
        EngineConfig(
            hermes_bin=hermes,
            docker_bin="docker",
            hermes_home=tmp_path / "shared",
            profile_prefix="agos-",
            sandbox_image="x",
            host_home=scratch_home,
            roots_dir=tmp_path / "roots",
            runtime_dir=tools if tools.is_dir() else None,
        ),
        egress=False,
    )


def _root(tmp_path: Path, provider: str, pool: dict[str, list[dict[str, object]]]) -> Path:
    root = tmp_path / "roots" / "agos-alpha"
    root.mkdir(parents=True)
    (root / "config.yaml").write_text(f"model:\n  provider: {provider}\n  default: x\n")
    (root / "auth.json").write_text(json.dumps({"version": 1, "credential_pool": pool}))
    return root


def test_an_own_hermes_login_needs_no_borrowing(engine: HermesEngine, tmp_path: Path) -> None:
    entry: dict[str, object] = {
        "id": "a1",
        "label": "anthropic-oauth-1",
        "source": "manual:hermes_pkce",
        "auth_type": "oauth",
        "access_token": "sk-ant-oat01-" + "x" * 24,
        "refresh_token": "r",
        "priority": 0,
        "last_status": "ok",
    }
    key: dict[str, object] = {"id": "b1", "label": "OPENROUTER_API_KEY"}
    key |= {"source": "env:OPENROUTER_API_KEY"}
    key |= {"auth_type": "api_key", "priority": 0, "last_status": "exhausted"}
    key |= {"last_error_message": "402 out of credits"}
    root = _root(tmp_path, "anthropic", {"anthropic": [entry], "openrouter": [key]})
    found = engine.hermes_logins(root, status=True)
    assert found["provider"] == "anthropic" and found["logged_in"] is True
    by = {e["provider"]: e for e in found["pool"]}
    assert by["anthropic"]["borrowed"] is False
    assert by["openrouter"]["borrowed"] is False  # the home's own .env line
    assert by["openrouter"]["last_status"] == "exhausted"
    assert by["openrouter"]["last_error_message"] == "402 out of credits"
    assert "sk-ant-oat01" not in json.dumps(found)  # no secret leaves Hermes's runtime
    assert not general_sync.borrowing_needed(engine, root)


def test_a_root_without_its_own_login_keeps_borrowing(engine: HermesEngine, tmp_path: Path) -> None:
    root = _root(tmp_path, "anthropic", {})
    found = engine.hermes_logins(root, status=True)
    assert found["logged_in"] is False
    assert general_sync.borrowing_needed(engine, root)


def test_a_key_provider_needs_no_borrowing(engine: HermesEngine, tmp_path: Path) -> None:
    root = _root(tmp_path, "openrouter", {})
    (root / ".env").write_text("OPENROUTER_API_KEY=sk-or-v1-" + "y" * 40 + "\n")
    found = engine.hermes_logins(root, status=True)
    assert found["logged_in"] is True  # no registry row: Hermes's pool says so
    assert not general_sync.borrowing_needed(engine, root)


def test_the_model_catalog_reads_hermess_structured_pool(
    engine: HermesEngine, tmp_path: Path
) -> None:
    """P7 + P2: the catalog's pool is Hermes's own redacted list (no regex over
    `hermes auth list`), run with Hermes's own runtime command."""
    from agos_core.engine.models import ModelCatalog, hermes_repo

    key: dict[str, object] = {"id": "b1", "label": "OPENROUTER_API_KEY", "priority": 0}
    key |= {"source": "env:OPENROUTER_API_KEY", "auth_type": "api_key"}
    root = _root(tmp_path, "openrouter", {"openrouter": [key]})
    (root / ".env").write_text("OPENROUTER_API_KEY=sk-or-v1-" + "z" * 40 + "\n")
    found = ModelCatalog(engine.settings).pool(root)
    assert [(c.slug, c.kind) for c in found] == [("openrouter", "api_key")]
    repo = hermes_repo(engine.settings)
    assert repo is not None and (repo / "hermes_cli").is_dir()
