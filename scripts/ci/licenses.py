#!/usr/bin/env python3
"""Dependency licence gate: every dependency's licence must be one an MIT project can ship with.

    python3 scripts/ci/licenses.py node [pnpm-licenses.json]   # `pnpm licenses list --json -r`
    uv run python ../../scripts/ci/licenses.py python          # the core's environment
    ... --list                                                 # print every package and licence

The allowed licence ids and the reviewed exceptions (a package whose licence is not on
the list but is fine where AGOS uses it, with the reason) live in
scripts/ci/licenses-allowed.json. A package fails when its licence is not allowed and
it is not an exception with that same licence; a new or changed licence therefore needs
a review, never a silent pass. An "A OR B" licence passes when one side is allowed,
"A AND B" when both are.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path

POLICY = Path(__file__).with_name("licenses-allowed.json")

# What Python packages write instead of an SPDX id (License field or trove classifier).
ALIASES = {
    "mit license": "MIT",
    "the mit license": "MIT",
    "bsd license": "BSD-3-Clause",
    "bsd": "BSD-3-Clause",
    "new bsd license": "BSD-3-Clause",
    "apache software license": "Apache-2.0",
    "apache license 2.0": "Apache-2.0",
    "apache 2.0": "Apache-2.0",
    "mozilla public license 2.0 (mpl 2.0)": "MPL-2.0",
    "python software foundation license": "PSF-2.0",
    "isc license (iscl)": "ISC",
    "the unlicense (unlicense)": "Unlicense",
}
CLASSIFIER = "License :: "


def normalize(text: str) -> str:
    text = text.strip()
    return ALIASES.get(text.lower(), text)


def python_packages() -> dict[str, str]:
    """name -> licence of every installed distribution of this environment."""
    found: dict[str, str] = {}
    for dist in metadata.distributions():
        meta = dist.metadata
        name = meta["Name"]
        if not name:
            continue
        expression = meta.get("License-Expression")
        classifiers = [
            c.split(" :: ")[-1]
            for c in meta.get_all("Classifier") or []
            if c.startswith(CLASSIFIER) and c.count(" :: ") >= 2
        ]
        plain = (meta.get("License") or "").strip()
        if expression:
            lic = expression
        elif classifiers:
            lic = " OR ".join(sorted({normalize(c) for c in classifiers}))
        elif plain and len(plain) < 80 and "\n" not in plain:
            lic = normalize(plain)
        else:
            lic = "UNKNOWN"
        found[name.lower().replace("_", "-")] = lic
    return found


def node_packages(report: str | None) -> dict[str, str]:
    """name -> licence from `pnpm licenses list --json -r` (read from a file or run here)."""
    if report:
        text = Path(report).read_text()
    else:
        text = subprocess.run(
            ["pnpm", "licenses", "list", "--json", "-r"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    found: dict[str, str] = {}
    for lic, packages in json.loads(text).items():
        for package in packages:
            name = package["name"]  # versions under two licences: both must pass
            found[name] = (
                f"{found[name]} AND {lic}" if name in found and found[name] != lic else lic
            )
    return found


def allowed(lic: str, ids: set[str]) -> bool:
    lic = lic.strip()
    while lic.startswith("(") and lic.endswith(")"):
        lic = lic[1:-1].strip()
    alternatives = re.split(r"\s+OR\s+", lic)
    if len(alternatives) > 1:
        return any(allowed(a, ids) for a in alternatives)
    parts = re.split(r"\s+AND\s+", lic)
    if len(parts) > 1:
        return all(allowed(p, ids) for p in parts)
    return normalize(lic) in ids


def check(ecosystem: str, packages: dict[str, str], policy: dict) -> list[str]:
    ids = set(policy["allowed"])
    own = set(policy.get("own", []))
    exceptions = policy["exceptions"].get(ecosystem, {})
    problems = []
    for name, lic in sorted(packages.items()):
        if name in own or allowed(lic, ids):
            continue
        reviewed = exceptions.get(name)
        if reviewed and reviewed["license"] == lic:
            continue
        problems.append(f"{ecosystem}: {name} is {lic}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ecosystem", choices=["node", "python"])
    parser.add_argument("report", nargs="?", help="node: a saved `pnpm licenses list --json -r`")
    parser.add_argument("--list", action="store_true", help="print every package and licence")
    parser.add_argument("--policy", default=str(POLICY))
    args = parser.parse_args(argv)
    policy = json.loads(Path(args.policy).read_text())
    packages = node_packages(args.report) if args.ecosystem == "node" else python_packages()
    if args.list:
        for name, lic in sorted(packages.items()):
            print(f"{name}\t{lic}")
    problems = check(args.ecosystem, packages, policy)
    for problem in problems:
        print(f"::error::licence not allowed for an MIT project: {problem}")
    if problems:
        print(
            f"{len(problems)} package(s) need a licence review: drop the dependency, or add it "
            f"to the exceptions in {Path(args.policy).name} with the reason it is fine"
        )
        return 1
    print(f"licences: {len(packages)} {args.ecosystem} packages, all allowed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
