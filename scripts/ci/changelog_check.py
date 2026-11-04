#!/usr/bin/env python3
"""CHANGELOG gate for pull requests.

A PR that changes product code (apps/*/src, packages/*/src, services/*/src) must add a
line under `## [Unreleased]` in CHANGELOG.md. The workflow skips this check when the PR
carries the label `skip-changelog` (refactors, tests-only, CI).

    python3 scripts/ci/changelog_check.py <base-sha> [<head-sha>]
"""

from __future__ import annotations

import re
import subprocess
import sys

PRODUCT = re.compile(r"^(apps|packages|services)/[^/]+/src/")


def git(*args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def unreleased(text: str) -> str:
    match = re.search(
        r"^## \[Unreleased\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.MULTILINE | re.DOTALL
    )
    return match.group(1).strip() if match else ""


def main() -> int:
    base = sys.argv[1]
    head = sys.argv[2] if len(sys.argv) > 2 else "HEAD"
    changed = git("diff", "--name-only", f"{base}...{head}").split()
    product = [name for name in changed if PRODUCT.match(name)]
    if not product:
        print("changelog: no product code changed, nothing to check")
        return 0
    merge_base = git("merge-base", base, head).strip()
    try:
        before = git("show", f"{merge_base}:CHANGELOG.md")
    except subprocess.CalledProcessError:
        before = ""
    after = git("show", f"{head}:CHANGELOG.md")
    if unreleased(after) != unreleased(before) and unreleased(after):
        print(f"changelog: Unreleased has a new entry ({len(product)} product files changed)")
        return 0
    print("changelog: this PR changes product code but adds nothing under")
    print("'## [Unreleased]' in CHANGELOG.md. Add one line in plain words (what the user")
    print("sees), or label the PR 'skip-changelog' when no user sees a change. Files:")
    print("\n".join(f"  {name}" for name in product[:20]))
    return 1


if __name__ == "__main__":
    sys.exit(main())
