"""A workspace's skill goes the Hermes way: Hermes's curator archives it (recoverable,
in its ledger); AGOS never deletes a skill folder itself."""

from pathlib import Path

import pytest

from agos_core.engine.library import LibraryError, archive_skill, copies_dir


def _skill(folder: Path, text: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(text)


def test_hermes_kept_the_skill_is_said(tmp_path: Path) -> None:
    def refuse(skill: str) -> None:
        raise RuntimeError("curator: 'writing' is pinned")

    _skill(copies_dir(tmp_path) / "writing", "---\nname: writing\ndescription: x\n---\nv1\n")
    with pytest.raises(LibraryError, match="pinned"):
        archive_skill(tmp_path, "writing", archive=refuse)
    assert (copies_dir(tmp_path) / "writing" / "SKILL.md").is_file()


def test_no_rmtree_of_a_workspace_skill() -> None:
    src = Path(__file__).resolve().parents[1] / "src" / "agos_core" / "engine" / "library.py"
    text = src.read_text()
    body = text[text.index("def archive_skill(") : text.index("def write_mcp_env(")]
    assert "rmtree" not in body and "archive(" in body


def test_hermess_own_curator_archives_a_workspace_skill(tmp_path: Path) -> None:
    """The real `hermes curator archive`: the workspace's skill (a local skill of its
    root, in skills/agos-library) moves to skills/.archive/ and the curator's
    ledger records it."""
    import os
    import shutil
    import subprocess

    hermes = shutil.which("hermes")
    tools = Path.home() / ".hermes" / "tools"
    if not hermes or not tools.is_dir():
        pytest.skip("no Hermes install on this machine")
    home = tmp_path / "home"
    text = "---\nname: writing\ndescription: Write well.\n---\n\nv1\n"
    _skill(copies_dir(home) / "writing", text)
    (home / "config.yaml").write_text("skills:\n  external_dirs: []\n")
    env = {**os.environ, "HERMES_HOME": str(home), "HERMES_RUNTIME_DIR": str(tools)}

    def archive(skill: str) -> None:
        done = subprocess.run(  # noqa: S603 - fixed argv
            [hermes, "curator", "archive", skill],
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        assert done.returncode == 0, done.stdout + done.stderr

    archive_skill(home, "writing", archive=archive)
    assert not (copies_dir(home) / "writing").exists()
    assert (home / "skills" / ".archive" / "writing" / "SKILL.md").is_file()
    ledger = (home / "skills" / ".curator_ledger.jsonl").read_text()
    assert '"archive"' in ledger and "writing" in ledger
