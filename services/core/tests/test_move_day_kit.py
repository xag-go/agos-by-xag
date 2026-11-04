"""Move day knows the per-workspace Hermes roots (area3 B2, ADR 0020): each root is
Hermes's own `hermes backup` in the AGOS backup (hermes/roots/<name>.zip), put back
with Hermes's own `hermes import` into <roots>/<name>; the restore check and the
server check look at the roots; the PC's gateways (Hermes's systemd user services)
are stopped with systemd, never pkill, and the PC's data is never rm -rf'd."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DEPLOY = REPO / "deploy"
sys.path.insert(0, str(REPO / "services" / "core" / "scripts"))


def _zip(path: Path, files: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)


def test_each_root_is_put_back_by_hermes_import(tmp_path: Path) -> None:
    restored, roots = tmp_path / "restored", tmp_path / "data" / "hermes"
    for name in ("agos-a", "agos-b"):
        _zip(restored / "hermes" / "roots" / f"{name}.zip", {"config.yaml": "x: 1\n"})
    log = tmp_path / "calls.jsonl"
    fake = tmp_path / "hermes"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys, zipfile, pathlib\n"
        f"open({str(log)!r}, 'a').write(json.dumps({{'args': sys.argv[1:], "
        "'home': os.environ['HERMES_HOME'], 'runtime': os.environ.get('HERMES_RUNTIME_DIR')}) + '\\n')\n"
        "zipfile.ZipFile(sys.argv[-1]).extractall(os.environ['HERMES_HOME'])\n"
    )
    fake.chmod(0o755)
    env = {**os.environ, "HERMES_BIN": str(fake), "HERMES_RUNTIME_DIR": "/rt"}
    done = subprocess.run(  # noqa: S603 - the kit's own script
        [str(DEPLOY / "import-roots.sh"), str(restored), str(roots)],
        env=env, capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    calls = [json.loads(ln) for ln in log.read_text().splitlines()]
    assert [c["home"] for c in calls] == [str(roots / "agos-a"), str(roots / "agos-b")]
    assert all(c["args"][:2] == ["import", "--force"] and c["runtime"] == "/rt" for c in calls)
    assert (roots / "agos-a" / "config.yaml").is_file()
    # never over a root that is there
    again = subprocess.run(  # noqa: S603
        [str(DEPLOY / "import-roots.sh"), str(restored), str(roots)],
        env=env, capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    assert again.returncode != 0 and "already exists" in again.stderr


def test_the_restore_and_the_rehearsal_use_it() -> None:
    for script in ("place-restore.sh", "rehearse-in-container.sh"):
        assert "import-roots.sh" in (DEPLOY / script).read_text(), script


def test_restore_check_looks_at_every_root(tmp_path: Path) -> None:
    import restore_and_verify as rv  # type: ignore[import-not-found,unused-ignore]

    _zip(tmp_path / "hermes" / "roots" / "agos-a.zip", {"config.yaml": "x", "SOUL.md": "s"})
    _zip(tmp_path / "hermes" / "roots" / "agos-b.zip", {"SOUL.md": "s", "auth.json": "{}"})
    names, problems = rv.check_roots(tmp_path)
    assert names == ["agos-a", "agos-b"]
    assert any("agos-b" in p and "config.yaml" in p for p in problems)
    assert any("agos-b" in p and "auth.json" in p for p in problems)
    assert not any("agos-a" in p for p in problems)


def test_the_server_check_reads_soul_in_the_root() -> None:
    text = (DEPLOY / "verify-server.sh").read_text()
    assert ".hermes/profiles/agos-$ws/SOUL.md" not in text
    assert 'ROOTS="${AGOS_HERMES_ROOTS:-$DATA/hermes}"' in text
    assert '"$ROOTS/agos-$ws/SOUL.md"' in text


def test_hermes_backup_and_import_of_a_root_round_trip() -> None:
    """The real thing: Hermes's backup of one root, imported by the kit into an
    empty roots folder, gives the same home back. Never under ~/.hermes: Hermes's
    backup maps any home inside it to the owner's whole ~/.hermes
    (hermes_constants.get_default_hermes_root), as AGOS's roots never are."""
    cache = Path.home() / ".cache"
    cache.mkdir(exist_ok=True)
    base = Path(tempfile.mkdtemp(prefix="agos-move-kit-", dir=cache))
    try:
        home = base / "pc" / "agos-a"
        home.mkdir(parents=True)
        (home / "config.yaml").write_text("model:\n  provider: openrouter\n")
        (home / "SOUL.md").write_text("I am the Co-Founder.\n")
        env = {
            "HOME": str(Path.home()),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HERMES_HOME": str(home),
            "HERMES_RUNTIME_DIR": str(Path.home() / ".hermes" / "tools"),
        }
        out = base / "restored" / "hermes" / "roots" / "agos-a.zip"
        out.parent.mkdir(parents=True)
        made = subprocess.run(  # noqa: S603
            [str(shutil.which("hermes")), "backup", "-o", str(out)],
            env=env, capture_output=True, text=True, timeout=300, check=False,
        )  # fmt: skip
        assert made.returncode == 0 and out.is_file(), made.stderr[-500:]
        roots = base / "server" / "hermes"
        done = subprocess.run(  # noqa: S603
            [str(DEPLOY / "import-roots.sh"), str(base / "restored"), str(roots)],
            env={**env, "HERMES_BIN": str(shutil.which("hermes"))},
            capture_output=True, text=True, timeout=300, check=False,
        )  # fmt: skip
        assert done.returncode == 0, done.stdout[-500:] + done.stderr[-500:]
        assert (roots / "agos-a" / "SOUL.md").read_text() == "I am the Co-Founder.\n"
    finally:
        shutil.rmtree(base, ignore_errors=True)
