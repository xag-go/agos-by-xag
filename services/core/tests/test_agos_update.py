"""Settings → General → Update AGOS: the check is `git fetch` of the release branch
(read-only), "Update now" starts `agos update --yes` as its own systemd user
service, and the card follows the progress file `agos update` writes."""

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agos_core.actions import agos_update as actions
from agos_core.api.app import create_app
from agos_core.config import Settings


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", "-C", str(cwd), *args],  # noqa: S607
        capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip


@pytest.fixture
def release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """A published AGOS (bare repo) and the install's clone of it."""
    origin, app = tmp_path / "origin.git", tmp_path / "agos"
    src = tmp_path / "src"
    src.mkdir()
    _git(src, "init", "-q", "-b", "main")
    _git(src, "config", "user.email", "t@example.com")
    _git(src, "config", "user.name", "T")
    (src / "deploy").mkdir()
    (src / "deploy" / "hermes.pin").write_text("aaaa\n")
    (src / "VERSION").write_text("0.1.0\n")
    _git(src, "add", ".")
    _git(src, "commit", "-q", "-m", "First release")
    subprocess.run(["git", "clone", "-q", "--bare", str(src), str(origin)], check=True)  # noqa: S603,S607
    subprocess.run(["git", "clone", "-q", str(origin), str(app)], check=True)  # noqa: S603,S607
    conf = tmp_path / "agos.conf"
    conf.write_text(
        f"AGOS_USER=agos\nAGOS_APP={app}\nAGOS_REF=main\nAGOS_CHANNEL=main\nAGOS_LOCAL_REPO=\n"
    )
    monkeypatch.setattr(actions, "CONF", conf)
    monkeypatch.setenv("AGOS_APP_DIR", str(app))
    return src, origin


@pytest.fixture
def client(tmp_path: Path) -> Iterator[tuple[TestClient, Any]]:
    settings = Settings(
        data_dir=tmp_path / "data",
        internal_token_file=tmp_path / "data" / "system" / "internal.token",
        documents_url=None,
        engine=None,
    )
    application = create_app(settings, background=False)
    with TestClient(application) as c:
        c.headers["x-agos-internal"] = settings.internal_token_file.read_text()
        yield c, application.state.core


def _publish(src: Path, title: str, pin: str | None = None, version: str | None = None) -> None:
    (src / "NEWS").write_text(title)
    if version:
        (src / "VERSION").write_text(version + "\n")
    if pin:
        (src / "deploy" / "hermes.pin").write_text(pin + "\n")
    _git(src, "add", ".")
    _git(src, "commit", "-q", "-m", title)
    _git(src, "push", "-q", str(src.parent / "origin.git"), "main")


def test_check_is_read_only_and_lists_the_new_commits(release: Any, client: Any) -> None:
    src, _origin = release
    c, _core = client
    first = c.post("/agos-update/check").json()
    assert first["target"] is None and first["news"] == []
    assert first["target_version"] == "0.1.0"
    _publish(src, "Faster board", pin="bbbb", version="0.2.0")
    found = c.post("/agos-update/check").json()
    assert found["target"] and found["target"] != found["current"]
    assert found["target_version"] == "0.2.0"
    assert found["news"] == ["Faster board"]
    assert found["hermes_changes"] is True
    assert c.get("/agos-update").json()["current"]["version"] == "0.1.0"
    # read-only: the install's checkout did not move
    assert c.get("/agos-update").json()["current"]["sha"] == found["current"]


def test_update_now_starts_agos_update_outside_the_core(
    release: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    src, _origin = release
    c, core = client
    launched: list[list[str]] = []
    monkeypatch.setattr(actions, "_launch", launched.append)
    monkeypatch.setenv("AGOS_BIN", "/usr/local/bin/agos")
    assert c.post("/agos-update/run").status_code == 400  # never checked
    _publish(src, "New thing")
    c.post("/agos-update/check")
    started = c.post("/agos-update/run")
    assert started.status_code == 200, started.text
    assert started.json()["phase"] == "queued"
    (args,) = launched
    assert args[:2] == ["systemd-run", "--user"] and args[-3:] == [
        "/usr/local/bin/agos",
        "update",
        "--yes",
    ]
    # one at a time
    assert c.post("/agos-update/run").status_code == 400
    # the card reads what `agos update` writes
    actions.state_file(core).write_text(json.dumps({"phase": "done", "from": "a", "to": "b"}))
    assert c.get("/agos-update").json()["state"]["phase"] == "done"


def test_an_install_from_a_folder_is_not_updated_from_here(
    release: Any, client: Any, tmp_path: Path
) -> None:
    c, _core = client
    conf = actions.CONF
    conf.write_text(conf.read_text().replace("AGOS_LOCAL_REPO=", "AGOS_LOCAL_REPO=/src"))
    assert c.get("/agos-update").json()["installed"] is False
    assert c.post("/agos-update/check").status_code == 400


def test_a_stale_running_state_does_not_block_forever() -> None:
    assert actions.running({"phase": "build", "started_at": actions._now()})
    assert not actions.running({"phase": "build", "started_at": "2020-01-01T00:00:00+00:00"})
    assert not actions.running({"phase": "done"})


def _tag(src: Path, tag: str) -> None:
    _git(src, "tag", "-a", tag, "-m", tag)
    _git(src, "push", "-q", str(src.parent / "origin.git"), tag)


def test_the_stable_channel_offers_the_newest_release_not_main(release: Any, client: Any) -> None:
    src, _origin = release
    c, _core = client
    conf = actions.CONF
    conf.write_text(conf.read_text().replace("AGOS_CHANNEL=main", "AGOS_CHANNEL=stable"))
    assert c.post("/agos-update/check").json()["target"] is None  # no release yet
    _publish(src, "Hotfix", version="0.1.1")
    _tag(src, "v0.1.1")
    _publish(src, "Beta board", version="0.2.0")
    _tag(src, "v0.2.0-beta.1")
    _publish(src, "Unreleased work")
    found = c.post("/agos-update/check").json()
    assert found["channel"] == "stable" and found["release"] == "v0.1.1"
    assert found["news"] == ["Hotfix"] and found["target_version"] == "0.1.1"
    conf.write_text(conf.read_text().replace("AGOS_CHANNEL=stable", "AGOS_CHANNEL=beta"))
    found = c.post("/agos-update/check").json()
    assert found["release"] == "v0.2.0-beta.1" and found["news"] == ["Beta board", "Hotfix"]


def test_an_install_past_the_newest_release_is_up_to_date(
    release: Any, client: Any, tmp_path: Path
) -> None:
    """Only forward: an install that followed main is never offered the older release."""
    src, _origin = release
    c, _core = client
    _publish(src, "Hotfix")
    _tag(src, "v0.1.1")
    _publish(src, "Newer work on main")
    _git(tmp_path / "agos", "pull", "-q", "--ff-only", "origin", "main")
    conf = actions.CONF
    conf.write_text(conf.read_text().replace("AGOS_CHANNEL=main\n", ""))  # an old install
    found = c.post("/agos-update/check").json()
    assert found["channel"] == "stable" and found["target"] is None and found["news"] == []
