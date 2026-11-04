"""The public repository is named once per installer, and only the real one is named
anywhere: a one-liner pointing at a wrong (or later squatted) GitHub name would make
`curl ... | bash` run someone else's script (security audit 10.1 / F3)."""

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PUBLIC = "xag-go/agos-by-xag"
OLD = ("xaliensgroup/xag-agos", "xaliensgroup/agos")


def _tracked() -> list[Path]:
    out = subprocess.run(  # noqa: S603 — fixed argv
        ["git", "-C", str(REPO), "ls-files", "-z"],  # noqa: S607 — git on PATH
        capture_output=True,
        check=True,
    ).stdout.decode()
    return [REPO / name for name in out.split("\0") if name]


def test_no_old_repository_name_is_left() -> None:
    me = Path(__file__).resolve()
    found = []
    for path in _tracked():
        if path.resolve() == me or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found += [f"{path.relative_to(REPO)}: {old}" for old in OLD if old in text]
    assert found == []


def test_each_installer_names_the_repository_in_one_place() -> None:
    sh = (REPO / "install.sh").read_text()
    ps1 = (REPO / "install.ps1").read_text()
    assert f'AGOS_GITHUB_REPO="{PUBLIC}"' in sh
    assert f"$GitHubRepo = '{PUBLIC}'" in ps1
    # The URLs are built from that constant: besides it, only the usage comment.
    assert sh.count(PUBLIC) == 2 and ps1.count(PUBLIC) == 2
    server = (REPO / "deploy" / "install-server.sh").read_text()
    assert f"https://github.com/{PUBLIC}.git" in server
