#!/usr/bin/env python3
"""Cutting an AGOS release (docs/releases.md). Never pushes, never publishes.

    scripts/release.py prepare <version>   VERSION, the README badge and CHANGELOG's
                                           [Unreleased] -> [<version>] - <today>, one commit,
                                           then the annotated tag v<version> (signed with
                                           the owner's git signing key when one is set)
    scripts/release.py check <tag>         the tag is a release: its grammar, VERSION,
                                           its CHANGELOG section (the release workflow's gate)
    scripts/release.py notes <version>     that CHANGELOG section (the release's notes)
    scripts/release.py manifest <tag>      release.json for the tagged commit (signed by the workflow)

Versions are SemVer starting at 0.x: X.Y.Z, or X.Y.Z-beta.N / X.Y.Z-rc.N for the beta
channel (ADR 0028). Standard library only: the release workflow runs it before any setup.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-(beta|rc)\.(\d+))?$")
UNRELEASED = "## [Unreleased]"
BADGE = re.compile(r"(badge/version-v)[0-9A-Za-z.\-_]+?(_\(beta\))?(-blue)")


class ReleaseError(Exception):
    """A release that can't be cut or published as asked (the message says why)."""


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def parse(version: str) -> tuple[int, int, int, str, int]:
    match = VERSION_RE.match(version)
    if not match:
        raise ReleaseError(f"'{version}' is not a release version (X.Y.Z or X.Y.Z-beta.N / -rc.N)")
    major, minor, patch, pre, n = match.groups()
    return int(major), int(minor), int(patch), pre or "", int(n or 0)


def section(changelog: str, version: str) -> str:
    """The body of CHANGELOG's `## [<version>]` section ("" when there is none)."""
    head = re.compile(rf"^## \[{re.escape(version)}\][^\n]*\n", re.M)
    found = head.search(changelog)
    if not found:
        return ""
    rest = changelog[found.end() :]
    end = re.search(r"^## \[|^\[[^\]]+\]: ", rest, re.M)
    return (rest[: end.start()] if end else rest).strip()


def bump_changelog(changelog: str, version: str, today: str) -> str:
    """[Unreleased] becomes [<version>] - <today> under a new, empty [Unreleased]."""
    if f"## [{version}]" in changelog:
        raise ReleaseError(f"CHANGELOG.md already has a [{version}] section")
    if UNRELEASED not in changelog:
        raise ReleaseError("CHANGELOG.md has no [Unreleased] section")
    body = section(changelog.replace(UNRELEASED, "## [Unreleased-body]", 1), "Unreleased-body")
    if not body:
        raise ReleaseError("CHANGELOG.md's [Unreleased] section is empty: nothing to release")
    out = changelog.replace(UNRELEASED, f"{UNRELEASED}\n\n## [{version}] - {today}", 1)
    link = f"[{version}]: https://github.com/xag-go/agos-by-xag/releases/tag/v{version}\n"
    return out if link in out else out.rstrip("\n") + "\n" + link


def bump_badge(readme: str, version: str) -> str:
    beta = "_(beta)" if version.startswith("0.") or "-" in version else ""
    shown = version.replace("-", "--")  # shields.io: "--" is a literal dash
    out, n = BADGE.subn(lambda m: f"{m.group(1)}{shown}{beta}{m.group(3)}", readme, count=1)
    if n != 1:
        raise ReleaseError("README.md has no version badge (badge/version-v...)")
    return out


def prepare(version: str, today: str | None = None, root: Path = ROOT) -> str:
    """The release commit and its tag, locally. Returns the tag."""
    parse(version)
    tag = f"v{version}"
    if git("status", "--porcelain", "--untracked-files=no", cwd=root):
        raise ReleaseError("the working tree has changes: commit or stash them first")
    if git("tag", "-l", tag, cwd=root):
        raise ReleaseError(f"the tag {tag} exists already")
    today = today or dt.datetime.now(dt.UTC).date().isoformat()
    changelog = root / "CHANGELOG.md"
    changelog.write_text(bump_changelog(changelog.read_text(), version, today))
    readme = root / "README.md"
    readme.write_text(bump_badge(readme.read_text(), version))
    (root / "VERSION").write_text(version + "\n")
    git("add", "VERSION", "README.md", "CHANGELOG.md", cwd=root)
    git("commit", "-q", "-m", f"Release {version}", cwd=root)
    signed = bool(subprocess.run(
        ["git", "config", "--get", "user.signingkey"],  # noqa: S607
        cwd=root, capture_output=True, text=True, check=False,
    ).stdout.strip())  # fmt: skip
    git("tag", "-s" if signed else "-a", tag, "-m", f"AGOS {version}", cwd=root)
    return tag


def check(tag: str, root: Path = ROOT) -> None:
    """The release workflow's gate: the tag, VERSION and CHANGELOG agree."""
    if not tag.startswith("v"):
        raise ReleaseError(f"'{tag}' is not a release tag (v<version>)")
    version = tag[1:]
    parse(version)
    found = (root / "VERSION").read_text().strip()
    if found != version:
        raise ReleaseError(f"VERSION says {found}, the tag says {version}")
    if not section((root / "CHANGELOG.md").read_text(), version):
        raise ReleaseError(f"CHANGELOG.md has no (or an empty) [{version}] section")


def manifest(tag: str, root: Path = ROOT) -> dict[str, str]:
    commit = git("rev-parse", f"{tag}^{{commit}}", cwd=root)
    return {
        "tag": tag,
        "version": tag.removeprefix("v"),
        "commit": commit,
        "tree": git("rev-parse", f"{commit}^{{tree}}", cwd=root),
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in {"prepare", "check", "notes", "manifest"}:
        print(__doc__, file=sys.stderr)
        return 2
    what, value = argv
    try:
        if what == "prepare":
            tag = prepare(value)
            print(f"Made the commit 'Release {value}' and the tag {tag} here (nothing pushed).")
            print(f"Publish (the owner, by hand): git push origin main {tag}")
        elif what == "check":
            check(value)
            print(f"{value}: VERSION and CHANGELOG agree")
        elif what == "notes":
            notes = section((ROOT / "CHANGELOG.md").read_text(), value.removeprefix("v"))
            if not notes:
                raise ReleaseError(f"CHANGELOG.md has no [{value}] section")
            print(notes)
        else:
            print(json.dumps(manifest(value), sort_keys=True))
    except (ReleaseError, subprocess.CalledProcessError) as error:
        print(f"release: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
