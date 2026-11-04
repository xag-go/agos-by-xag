"""Backup → restore into an EMPTY temp place → everything identical (step 9)."""

import json
import logging
import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from test_engine_sync import FakeRunner, profile_dir

from agos_core.actions import backups as backup_actions
from agos_core.api.app import create_app
from agos_core.config import EngineConfig, Settings
from agos_core.engine import backup as bk

MODEL = {"provider": "claude", "mode": "cli", "model": "claude-sonnet-5", "effort": "high"}
PASSWORD = "correct horse battery"  # noqa: S105 - test fixture
REAL_PRIVATE = backup_actions.hermes_private  # before the fixture stubs it


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Any, Path]]:
    hermes_home = tmp_path / "home" / ".hermes"
    hermes_home.mkdir(parents=True)
    monkeypatch.setenv("AGOS_BACKUP_DIR", str(tmp_path / "backups"))
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
        core.engine.start = lambda workspace_id, **_: None
        core.engine.is_running = lambda workspace_id: False
        core.engine.stop = lambda workspace_id, **_: None
        client.headers["x-agos-internal"] = settings.internal_token_file.read_text()
        from agos_core.actions import backups

        # Hermes's own list of credential stores (profile_path_is_private), as far as
        # these tests go; the real one is asked in test_hermes_says_which_files_hold_keys.
        monkeypatch.setattr(backups, "hermes_private", lambda core: _hermes_private)
        yield client, core, tmp_path


def _hermes_private(parts: list[tuple[str, ...]]) -> list[bool]:
    return [bool(p) and p[0] in ("pairing", "vault", "mcp-tokens") for p in parts]


def fill(client: TestClient, core: Any, tmp: Path) -> str:
    ws = client.post(
        "/workspaces", json={"name": "Argan", "description": "Oil shop", "defaultModel": MODEL}
    ).json()["id"]
    client.put(f"/workspaces/{ws}/memory/memory", json={"entries": ["Sells to hotels"]})
    client.put(f"/workspaces/{ws}/identity", json={"identity": "You run the argan shop."})
    client.post(
        f"/workspaces/{ws}/automations",
        json={
            "name": "Brief",
            "instructions": "Sum up",
            "schedule": "0 8 * * *",
            "model": MODEL,
            "on": False,
        },
    )
    made = client.post(
        f"/workspaces/{ws}/skills",
        json={
            "name": "voice",
            "definition": {"text": "---\nname: voice\ndescription: d\n---\n\nbody\n"},
        },
    )
    assert made.status_code == 201, made.text
    files = core.layout.workspaces / ws / "files"
    (files / "orders.csv").write_text("id,qty\n1,3\n")
    home = profile_dir(tmp / "home" / ".hermes", f"agos-{ws}")
    (home / "auth.json").write_text('{"secret": "never copied"}')
    (home / "cache").mkdir(exist_ok=True)
    (home / "cache" / "big.bin").write_bytes(b"x" * 1000)
    (home / "cron").mkdir(exist_ok=True)
    (home / "cron" / "jobs.json").write_text('{"jobs": []}')
    sqlite3.connect(home / "state.db").close()  # Hermes's sessions
    return str(ws)


def test_backup_then_restore_into_an_empty_place_is_identical(env: Any) -> None:
    client, core, tmp = env
    ws = fill(client, core, tmp)
    assert client.post("/backups/run").status_code == 400  # no password yet
    assert client.put("/backups/password", json={"password": "short"}).status_code == 422
    assert client.put("/backups/password", json={"password": PASSWORD}).status_code == 204
    made = client.post("/backups/run").json()
    assert made["name"].startswith("agos-backup-") and made["size"] > 0
    raw = (tmp / "backups" / made["name"]).read_bytes()
    assert b"orders.csv" not in raw and b"Sells to hotels" not in raw  # encrypted
    result = client.post("/backups/rehearse", json={}).json()
    assert result["ok"], (result["detail"], result["tables"])
    for table in (
        "workspaces",
        "chats",
        "automations",
        "library_items",
    ):
        live, back = result["tables"][table]
        assert live == back and live >= 1, table
    # Restore by hand into an empty place and look inside.
    target = tmp / "restored"
    manifest = bk.restore(tmp / "backups" / made["name"], PASSWORD, target)
    assert (
        target / "agos-data" / "workspaces" / ws / "files" / "orders.csv"
    ).read_text() == "id,qty\n1,3\n"
    # The workspace's root is Hermes's own backup (`hermes import` restores it),
    # sealed inside; so is the shared home (General Settings' login and keys).
    import zipfile

    assert (target / bk.HERMES_ZIP).is_file()
    with zipfile.ZipFile(target / f"{bk.ROOTS_PREFIX}agos-{ws}.zip") as zf:
        names = set(zf.namelist())
        assert zf.read("memories/MEMORY.md").decode() == "Sells to hotels"
        assert "You run the argan shop." in zf.read("SOUL.md").decode()
    assert "cron/jobs.json" in names
    # A workspace's skills live in its root: inside Hermes's own backup of it.
    assert "skills/agos-library/voice/SKILL.md" in names
    assert not (target / "hermes" / "profiles").exists()  # no copy of AGOS's own any more
    # Hermes's part is only ever Hermes's own `hermes backup` zips.
    hermes_files = [f for f in manifest.files if not f.startswith("agos-data/")]
    assert hermes_files and all(
        f == bk.HERMES_ZIP or (f.startswith(bk.ROOTS_PREFIX) and f.endswith(".zip"))
        for f in hermes_files
    )
    assert not [n for n in names if n.endswith("auth.json")]  # logins never travel
    db = sqlite3.connect(target / "agos-data" / "system" / "agos.db")
    # The name is the Co-Founder's Hermes display name: in the root's own Hermes backup.
    assert db.execute("SELECT id FROM workspaces").fetchone()[0] == "argan"
    assert all(len(v) == 64 for v in manifest.files.values())
    status = client.get("/backups").json()
    assert status["lastBackupOk"] and status["lastRehearsal"].startswith("OK")


def test_restore_refuses_live_data_wrong_password_and_tampering(env: Any) -> None:
    client, core, tmp = env
    fill(client, core, tmp)
    client.put("/backups/password", json={"password": PASSWORD})
    name = client.post("/backups/run").json()["name"]
    path = tmp / "backups" / name
    busy = tmp / "busy"
    busy.mkdir()
    (busy / "keep.txt").write_text("mine")
    with pytest.raises(bk.BackupError, match="empty"):
        bk.restore(path, PASSWORD, busy)
    assert (busy / "keep.txt").read_text() == "mine"
    with pytest.raises(bk.BackupError, match="Wrong password"):
        bk.restore(path, "not the password!", tmp / "r1")
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    bad = tmp / "backups" / "tampered.agosb"
    bad.write_bytes(bytes(data))
    with pytest.raises(bk.BackupError):
        bk.restore(bad, PASSWORD, tmp / "r2")
    cut = tmp / "backups" / "cut.agosb"
    cut.write_bytes(path.read_bytes()[:-100])
    with pytest.raises(bk.BackupError):
        bk.restore(cut, PASSWORD, tmp / "r3")


def test_keep_n_and_schedule(env: Any) -> None:
    client, core, _tmp = env
    client.put("/backups/password", json={"password": PASSWORD})
    client.put("/backups/schedule", json={"schedule": "daily", "keep": 2})
    import time

    for _ in range(3):
        client.post("/backups/run")
        time.sleep(1.1)
    assert len(client.get("/backups").json()["files"]) == 2
    from agos_core.actions import backups

    assert not backups.due(core)
    client.put("/backups/schedule", json={"schedule": "off", "keep": 2})
    assert not backups.due(core)
    status = client.get("/backups").json()
    assert status["diskTotalGb"] > 0 and json.dumps(status)


def test_a_rehearsal_checks_hermes_own_backup(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A workspace root's Hermes backup without its home fails the rehearsal."""
    client, core, tmp = env
    fill(client, core, tmp)
    client.put("/backups/password", json={"password": PASSWORD})
    real = core.engine.backup_root

    def without_config(workspace_id: str, out: Path, **kw: Any) -> None:
        import zipfile

        real(workspace_id, out, **kw)
        kept = tmp / "kept.zip"
        with zipfile.ZipFile(out) as src, zipfile.ZipFile(kept, "w") as dst:
            for name in src.namelist():
                if not name.endswith("config.yaml"):
                    dst.writestr(name, src.read(name))
        kept.replace(out)

    monkeypatch.setattr(core.engine, "backup_root", without_config)
    client.post("/backups/run")
    result = client.post("/backups/rehearse", json={}).json()
    assert not result["ok"] and any("config.yaml missing" in m for m in result["missing"])


# ---- no key in a backup (ADR 0023) -------------------------------------------------

# Built at run time: the repo holds no key-looking literal.
FAKE = {
    "OPENROUTER_API_KEY": "sk-or-v1-" + "f" * 40 + "A1b2",
    "TELEGRAM_BOT_TOKEN": "7012345678:" + "T" * 35,
    "ANTHROPIC_API_KEY": "sk-ant-" + "q" * 40,
}


def _plain(path: Path, tmp: Path) -> Path:
    """The backup's tar, decrypted (what anyone with the password would see)."""
    out = tmp / "opened.tar.gz"
    bk._open_stream(path, lambda salt: bk._key(PASSWORD, salt), out)
    return out


def _everything(tar_path: Path) -> dict[str, bytes]:
    """Every file in the backup, the files inside Hermes's zips included."""
    import io
    import tarfile
    import zipfile

    out: dict[str, bytes] = {}
    with tarfile.open(tar_path, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            handle = tar.extractfile(member)
            assert handle is not None
            data = handle.read()
            out[member.name] = data
            if member.name.endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    out |= {f"{member.name}!{n}": zf.read(n) for n in zf.namelist()}
    return out


def _with_keys(client: TestClient, core: Any, tmp: Path) -> str:
    ws = fill(client, core, tmp)
    shared = tmp / "home" / ".hermes"
    (shared / ".env").write_text(f"OPENROUTER_API_KEY={FAKE['OPENROUTER_API_KEY']}\n")
    root = core.engine.root(ws)
    (root / ".env").write_text(
        f"# the bot\nTELEGRAM_BOT_TOKEN={FAKE['TELEGRAM_BOT_TOKEN']}\n"
        f"export ANTHROPIC_API_KEY={FAKE['ANTHROPIC_API_KEY']}\n"
    )
    (root / "pairing").mkdir(exist_ok=True)
    (root / "pairing" / "telegram-approved.json").write_text('{"555": "owner"}')
    (root / "agos.token").write_text("tok" * 10)
    member = root / "profiles" / "a-writer"
    member.mkdir(parents=True, exist_ok=True)
    (member / ".env").write_text(f"OPENROUTER_API_KEY={FAKE['OPENROUTER_API_KEY']}\n")
    (member / ".credentials.json").write_text('{"x": 1}')
    from agos_core.actions import composio

    composio.store(core, ws, "composio-" + "c" * 30)
    return ws


def test_a_backup_holds_no_key_and_says_which_to_re_enter(env: Any) -> None:
    client, core, tmp = env
    ws = _with_keys(client, core, tmp)
    client.put("/backups/password", json={"password": PASSWORD})
    made = client.post("/backups/run")
    assert made.status_code == 201, made.text
    path = tmp / "backups" / made.json()["name"]
    files = _everything(_plain(path, tmp))
    names = [n.rsplit("!", 1)[-1].rsplit("/", 1)[-1] for n in files]
    for gone in (".env", "auth.json", "master.key", "internal.token", "agos.token"):
        assert gone not in names, gone
    assert ".credentials.json" not in names
    assert not [n for n in files if "/pairing/" in n or "!pairing/" in n]
    blob = b"".join(files.values())
    for value in [*FAKE.values(), "composio-" + "c" * 30]:
        assert value.encode() not in blob, value[:12]
    # No sealed value is left in AGOS's database copy (nothing for a key to open).
    assert not bk._SEALED.search(files["./agos-data/system/agos.db"].decode("latin-1"))
    manifest = json.loads(files["./manifest.json"])
    keys_out = manifest["keys_out"]
    listed = {(k["name"], k["where"]) for k in keys_out["keys"]}
    root = f"agos-{ws}"
    assert ("OPENROUTER_API_KEY", "shared home") in listed
    assert ("TELEGRAM_BOT_TOKEN", root) in listed and ("ANTHROPIC_API_KEY", root) in listed
    assert ("OPENROUTER_API_KEY", f"{root}, member a-writer") in listed
    assert (f"composio_key:{ws}", "AGOS") in listed
    assert all(set(k) == {"name", "where"} for k in keys_out["keys"])  # names only
    assert {"where": "AGOS data", "path": "system/master.key"} in keys_out["files"]
    # The rehearsal restores it and says what to re-enter.
    result = client.post("/backups/rehearse", json={}).json()
    assert result["ok"], (result["detail"], result["missing"])
    assert "Re-enter these keys in Settings → Keys:" in result["detail"]
    assert f"TELEGRAM_BOT_TOKEN (workspace {ws})" in result["detail"]
    assert "OPENROUTER_API_KEY (shared home)" in result["reenter"]
    # A real restore opens with no master key: the restored AGOS makes a new one.
    target = tmp / "restored"
    restored = bk.restore(path, PASSWORD, target)
    assert not (target / "agos-data" / "system" / "master.key").exists()
    assert f"TELEGRAM_BOT_TOKEN (agos-{ws})" in restored.reenter()
    db = sqlite3.connect(target / "agos-data" / "system" / "agos.db")
    assert db.execute(
        "SELECT count(*) FROM app_settings WHERE key IN ('backup_password', ?)",
        (f"composio_key:{ws}",),
    ).fetchone() == (0,)
    assert db.execute("SELECT count(*) FROM workspaces").fetchone()[0] == 1


def test_a_backup_made_before_still_restores(env: Any) -> None:
    """An older backup (keys inside, no keys_out list) restores as it is."""
    import io
    import tarfile

    client, core, tmp = env
    fill(client, core, tmp)
    client.put("/backups/password", json={"password": PASSWORD})
    name = client.post("/backups/run").json()["name"]
    path = tmp / "backups" / name
    plain = _plain(path, tmp)
    old = tmp / "old.tar.gz"
    with tarfile.open(plain, "r:gz") as src, tarfile.open(old, "w:gz") as dst:
        for member in src.getmembers():
            handle = src.extractfile(member) if member.isfile() else None
            data = handle.read() if handle is not None else b""
            if member.name == "./manifest.json":
                manifest = json.loads(data)
                manifest.pop("keys_out")
                manifest["files"]["agos-data/system/master.key"] = (
                    __import__("hashlib").sha256(b"old-key").hexdigest()
                )
                data = json.dumps(manifest).encode()
                member.size = len(data)
            dst.addfile(member, io.BytesIO(data) if member.isfile() else None)
        extra = tarfile.TarInfo("./agos-data/system/master.key")
        extra.size = len(b"old-key")
        dst.addfile(extra, io.BytesIO(b"old-key"))
    import secrets

    salt = secrets.token_bytes(16)
    sealed = tmp / "backups" / "agos-backup-19990101-000000.agosb"
    bk._seal_stream(old, sealed, bk._key(PASSWORD, salt), salt)
    manifest = bk.restore(sealed, PASSWORD, tmp / "restored-old")
    assert manifest.keys_out is None and manifest.reenter() == []
    assert (tmp / "restored-old" / "agos-data" / "system" / "master.key").read_bytes() == b"old-key"
    from agos_core.actions import backups

    assert backups.reenter_text(core, manifest) == ""
    result = client.post("/backups/rehearse", json={"name": sealed.name}).json()
    assert result["files"] > 0 and result["reenter"] == []


def test_hermes_says_which_files_hold_keys(tmp_path: Path) -> None:
    """Hermes's own profile_path_is_private, asked in its runtime (where installed)."""
    import shutil
    from types import SimpleNamespace

    hermes = shutil.which("hermes")
    if hermes is None:
        pytest.skip("no Hermes install on this machine")
    tools = Path.home() / ".hermes" / "tools"
    settings = EngineConfig(
        hermes_bin=hermes,
        docker_bin="docker",
        hermes_home=tmp_path / "hermes",
        profile_prefix="agos-",
        sandbox_image="x",
        host_home=Path.home(),
        roots_dir=tmp_path / "roots",
        runtime_dir=tools if tools.is_dir() else None,
    )
    ask = REAL_PRIVATE(cast(Any, SimpleNamespace(engine=SimpleNamespace(settings=settings))))
    assert ask is not None
    parts = [("pairing", "x.json"), ("memories", "MEMORY.md"), ("google_token.json",)]
    assert ask(parts) == [True, False, True]


def _agos_db(path: Path) -> None:
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE app_settings (key TEXT, value TEXT)")
    db.commit()
    db.close()


def test_a_file_gone_since_the_walk_is_left_out_not_a_failed_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """VM run: the dead-man check removed system/deadman.state between the backup's
    walk and its copy; the whole backup (and the update before it) failed on ENOENT."""
    data = tmp_path / "data"
    (data / "system").mkdir(parents=True)
    _agos_db(data / "system" / "agos.db")
    (data / "system" / "deadman.state").write_text('{"since": 1}')
    (data / "system" / "gone.db").write_bytes(b"")
    (data / "system" / "kept.txt").write_text("kept")
    walk = bk._walk

    def walk_then_delete(root: Path, exclude: tuple[Path, ...] = ()) -> Iterator[Path]:
        found = list(walk(root, exclude))
        (data / "system" / "deadman.state").unlink()
        (data / "system" / "gone.db").unlink()
        yield from found

    monkeypatch.setattr(bk, "_walk", walk_then_delete)
    staging = tmp_path / "staging"
    staging.mkdir()
    with caplog.at_level(logging.INFO, logger="agos"):
        manifest = bk.collect(data, staging)
    assert sorted(manifest.files) == ["agos-data/system/agos.db", "agos-data/system/kept.txt"]
    assert not (staging / "agos-data" / "system" / "gone.db").exists()
    # Review L3: what was left out is said, by path.
    said = [r.getMessage() for r in caplog.records if "vanished" in r.getMessage()]
    assert any("system/deadman.state" in m for m in said), said
    assert any("system/gone.db" in m for m in said), said


def test_a_backup_without_agos_db_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review L3: the database is the backup's whole point. Missing at the walk, or
    gone during the copy, the backup fails instead of passing without it."""
    data = tmp_path / "data"
    (data / "system").mkdir(parents=True)
    (data / "system" / "kept.txt").write_text("kept")
    staging = tmp_path / "staging"
    staging.mkdir()
    with pytest.raises(bk.BackupError, match=r"agos\.db"):
        bk.collect(data, staging)
    db = data / "system" / "agos.db"
    _agos_db(db)
    walk = bk._walk

    def walk_then_delete(root: Path, exclude: tuple[Path, ...] = ()) -> Iterator[Path]:
        found = list(walk(root, exclude))
        db.unlink()
        yield from found

    monkeypatch.setattr(bk, "_walk", walk_then_delete)
    with pytest.raises(bk.BackupError, match=r"agos\.db"):
        bk.collect(data, tmp_path / "staging2")


def test_a_file_that_cannot_be_read_still_fails_the_backup(tmp_path: Path) -> None:
    data = tmp_path / "data"
    (data / "system").mkdir(parents=True)
    _agos_db(data / "system" / "agos.db")
    secret = data / "system" / "locked.txt"
    secret.write_text("x")
    secret.chmod(0)
    staging = tmp_path / "staging"
    staging.mkdir()
    try:
        if os.access(secret, os.R_OK):
            pytest.skip("running as root: every file is readable")
        with pytest.raises(PermissionError):
            bk.collect(data, staging)
    finally:
        secret.chmod(0o600)
