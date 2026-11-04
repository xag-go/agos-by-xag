"""A fresh install is neutral: it starts with no workspace, voice notes off, no
timezone of its own (Hermes then uses this server's), and its data in ~/agos-data
unless AGOS_DATA_DIR says otherwise. An install that already holds a value keeps it.
"""

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from test_library import env  # noqa: F401 - fixture

from agos_core.actions import hermes_managed, owner_time, today
from agos_core.api.app import create_app
from agos_core.config import ConfigError, Settings, load_settings


@pytest.fixture(autouse=True)
def _hermes_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hermes's settings schema's speech-to-text rows (hermes_stt_rig.py: from its source)."""
    from hermes_stt_rig import hermes_stt_fields

    from agos_core.engine.hermes import HermesEngine

    fields = hermes_stt_fields()
    monkeypatch.setattr(HermesEngine, "config_schema", lambda self: list(fields))


@pytest.fixture
def bare(tmp_path: Path) -> Iterator[tuple[TestClient, Any]]:
    """The core on an empty data folder, no engine."""
    settings = Settings(
        data_dir=tmp_path / "data",
        internal_token_file=tmp_path / "data" / "system" / "internal.token",
        documents_url=None,
    )
    app = create_app(settings, background=False)
    with TestClient(app) as client:
        client.headers["x-agos-internal"] = settings.internal_token_file.read_text()
        yield client, app.state.core


def _count(core: Any, table: str) -> int:
    return int(core.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def test_an_empty_data_folder_starts_with_no_workspace(bare: tuple[TestClient, Any]) -> None:
    client, core = bare
    assert client.get("/workspaces").json() == []
    assert _count(core, "workspaces") == 0
    # Old migrations that name a workspace id insert nothing on an empty database.
    assert _count(core, "doc_settings") == 0


def test_the_first_start_with_hermes_seeds_no_workspace(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    assert client.get("/workspaces").json() == []
    assert _count(core, "workspaces") == 0
    assert not list((core.layout.root / "workspaces").glob("*"))


def test_a_fresh_install_has_voice_notes_off_and_no_timezone(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    managed = core.engine.managed_config()
    assert managed.get("stt") == {"enabled": False}
    assert "timezone" not in managed  # Hermes: this server's own time
    assert owner_time.owner_zone(core) == ""
    voice = client.get("/preferences/hermes-voice").json()
    assert (voice["provider"], voice["model"]) == ("off", "")
    assert client.get("/preferences/timezone").json() == {"timezone": ""}


def test_an_install_that_chose_a_voice_provider_keeps_it(env: Any) -> None:  # noqa: F811
    _client, core, _runner, _home = env
    core.engine.managed_write(
        [("stt.provider", "gemini"), ("stt.gemini.model", "gemini-x")], ["stt.enabled"]
    )
    assert not any(k.startswith("stt.") for k in hermes_managed.move_once(core))
    assert core.engine.managed_config()["stt"] == {
        "provider": "gemini",
        "gemini": {"model": "gemini-x"},
    }


def test_today_is_the_owners_clock(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    _client, core, _runner, _home = env
    assert today.date_today(core) == datetime.now().astimezone().date().isoformat()
    far = "Pacific/Kiritimati"  # UTC+14: a different date from UTC for 14 hours a day
    monkeypatch.setattr(owner_time, "owner_zone", lambda _core: far)
    assert today.date_today(core) == datetime.now(ZoneInfo(far)).date().isoformat()


def test_the_data_folder_defaults_to_agos_data_in_the_home() -> None:
    assert load_settings({"HOME": "/home/x"}).data_dir == Path("/home/x/agos-data")
    settings = load_settings({"HOME": "/home/x", "AGOS_DATA_DIR": "/srv/agos"})
    assert settings.data_dir == Path("/srv/agos")
    assert settings.internal_token_file == Path("/srv/agos/system/internal.token")
    with pytest.raises(ConfigError):
        load_settings({"HOME": "/home/x", "AGOS_DATA_DIR": "relative/dir"})
