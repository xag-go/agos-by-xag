"""The release version has one source: the repository's VERSION file. The CLI
(`agos version`), the Update AGOS card (through the core), the README badge and the
changelog's newest release all show the same number."""

import re
from pathlib import Path

from agos_core.actions import agos_update

REPO = Path(__file__).resolve().parents[3]


def test_version_file_is_a_plain_release_number() -> None:
    text = (REPO / "VERSION").read_text()
    assert re.fullmatch(r"\d+\.\d+\.\d+\n", text), text


def test_readme_badge_and_changelog_show_the_version() -> None:
    found = (REPO / "VERSION").read_text().strip()
    readme = (REPO / "README.md").read_text()
    assert f"badge/version-v{found}" in readme
    changelog = (REPO / "CHANGELOG.md").read_text()
    newest = re.search(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.M)
    assert newest and newest.group(1) == found


def test_core_and_cli_read_the_version_file() -> None:
    assert agos_update.version(REPO) == (REPO / "VERSION").read_text().strip()
    assert '"$AGOS_APP/VERSION"' in (REPO / "deploy" / "agos").read_text()
