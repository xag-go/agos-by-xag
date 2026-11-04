#!/usr/bin/env python3
"""Print a one-line Markdown summary of a pytest junit file (for $GITHUB_STEP_SUMMARY).

The file is the one pytest just wrote in the same job, but it is still read with a
hardened parser: expat with no DTD at all (a DOCTYPE or an entity declaration is
refused, so no entity expansion or external fetch can happen), and only the first
<testsuite>'s attributes are kept. The runner's plain python3 has no defusedxml.

    python3 scripts/ci/junit_summary.py services/core/pytest.xml >> "$GITHUB_STEP_SUMMARY"
"""

from __future__ import annotations

import sys
from pathlib import Path
from xml.parsers import expat


class _Refused(ValueError):
    """The file declares a DTD or an entity: not a pytest junit file."""


def suite_attributes(data: bytes) -> dict[str, str]:
    """The first <testsuite> element's attributes ({} when there is none)."""
    found: dict[str, str] = {}

    def start(tag: str, attrs: dict[str, str]) -> None:
        if tag == "testsuite" and not found:
            found.update(attrs)

    def refuse(*_args: object) -> None:
        raise _Refused("DTD or entity declarations are not read")

    parser = expat.ParserCreate()
    parser.StartElementHandler = start
    parser.StartDoctypeDeclHandler = refuse
    parser.EntityDeclHandler = refuse
    parser.Parse(data, True)
    return found


def main() -> int:
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"### Core tests: no {path.name} (pytest did not finish)")
        return 0
    try:
        a = suite_attributes(path.read_bytes())
    except (expat.ExpatError, _Refused) as error:
        print(f"### Core tests: {path.name} not read ({error})")
        return 0
    print(
        f"### Core tests: {a.get('tests')} run, {a.get('failures')} failed, "
        f"{a.get('errors')} errors, {a.get('skipped')} skipped, "
        f"{float(a.get('time', 0)):.0f} s"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
