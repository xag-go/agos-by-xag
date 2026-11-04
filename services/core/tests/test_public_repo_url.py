"""The public repository is named once per installer, and only the real one is named
anywhere: a one-liner pointing at a wrong (or later squatted) GitHub name would make
`curl ... | bash` run someone else's script (security audit 10.1 / F3)."""

import hashlib
import re
import subprocess
from itertools import pairwise
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PUBLIC = "xag-go/agos-by-xag"
# Repository names this project had before it was published, kept as SHA-256 digests so the
# names themselves are written nowhere in the tree.
OLD_SHA256 = frozenset(
    {
        "d3fea8ca5dbf9969931b5acd299ae15dcd8bb758c18f42630317f6dc6127808b",
        "3f2aac3af26d046a4229e3b26ffd345f1b715e0c3d2ad287d4a14cdf10c523b7",
    }
)
_PATHLIKE = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+")


def _tracked() -> list[Path]:
    out = subprocess.run(  # noqa: S603 — fixed argv
        ["git", "-C", str(REPO), "ls-files", "-z"],  # noqa: S607 — git on PATH
        capture_output=True,
        check=True,
    ).stdout.decode()
    return [REPO / name for name in out.split("\0") if name]


def _slugs(text: str) -> set[str]:
    """Every `owner/name` pair in the text, also inside a longer path or URL, with and
    without a trailing `.git` or full stop."""
    out: set[str] = set()
    for run in _PATHLIKE.findall(text):
        for owner, name in pairwise(run.split("/")):
            for candidate in (name, name.removesuffix(".git"), name.rstrip(".")):
                out.add(f"{owner}/{candidate}")
    return out


def test_no_old_repository_name_is_left() -> None:
    found = []
    for path in _tracked():
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if any(hashlib.sha256(slug.encode()).hexdigest() in OLD_SHA256 for slug in _slugs(text)):
            found.append(f"{path.relative_to(REPO)}: a former repository name")
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
