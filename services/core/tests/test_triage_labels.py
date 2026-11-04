"""Every label the repository's forms, Dependabot and CI use is in .github/labels.json
(docs/triage.md), so `scripts/sync-labels.sh --apply` creates all of them."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _labels() -> dict[str, dict[str, str]]:
    found = json.loads((REPO / ".github" / "labels.json").read_text())
    return {label["name"]: label for label in found}


def test_labels_are_well_formed() -> None:
    labels = _labels()
    assert len(labels) == len(json.loads((REPO / ".github" / "labels.json").read_text()))
    for name, label in labels.items():
        assert re.fullmatch(r"[0-9a-f]{6}", label["color"]), name
        assert 0 < len(label["description"]) <= 100, name


def test_every_label_in_use_is_listed_and_documented() -> None:
    used: set[str] = set()
    github = REPO / ".github"
    for path in [*github.glob("ISSUE_TEMPLATE/*.yml"), github / "dependabot.yml"]:
        for match in re.finditer(r"^\s*labels:\s*\[([^\]]*)\]", path.read_text(), re.M):
            used |= {x.strip().strip('"') for x in match.group(1).split(",") if x.strip()}
    for path in github.glob("workflows/*.yml"):
        used |= set(re.findall(r"labels\.\*\.name, '([^']+)'", path.read_text()))
    assert {"bug", "enhancement", "needs-triage", "dependencies", "skip-changelog"} <= used
    assert used <= set(_labels()), used - set(_labels())
    triage = (REPO / "docs" / "triage.md").read_text()
    missing = [name for name in _labels() if f"`{name}`" not in triage]
    assert missing == [], f"docs/triage.md does not explain {missing}"
