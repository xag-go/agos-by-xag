"""scripts/release-private-paths.py: no private development path (the maintainer's
worktrees, notes, helper scripts, ssh host, audit folders or home folder) in the
docs that are published; the public export (scripts/publish-public.sh) runs it."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[3]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "agos_private_paths", REPO / "scripts/release-private-paths.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]
    return module


check = _load()


@pytest.mark.parametrize(
    "line",
    [
        "see ~/agos-wt/eng-audit/architecture.md",
        "the plan in ~/wiki/agos-engineering-plan.md",
        "run ~/agos-tools/lowprio.sh first",
        "ssh agos-local 'agos status'",
        "the audit (eng-audit/docs-ops.md)",
        "cd /home/someone/agos",
    ],
)
def test_each_kind_of_private_path_is_found(line: str) -> None:
    hits = check.scan({"docs/x.md": f"intro\n{line}\n"})
    assert len(hits) == 1 and hits[0].startswith("docs/x.md:2: ")


@pytest.mark.parametrize(
    "line",
    [
        "the backups are in /home/agos/agos-backups",
        "the CI user /home/agos-ci/.hermes",
        "the sandbox's /home/agent/.cache",
        "HOME=/home/x in the example",
        "Hermes reads ~/.hermes/config.yaml and AGOS ~/agos-data",
        "a <home>: /home/<user>/agos",
    ],
)
def test_paths_every_install_has_are_fine(line: str) -> None:
    assert check.scan({"docs/x.md": line}) == []


def test_the_published_docs_have_no_private_path() -> None:
    files = check._read_tree(REPO, False)
    assert "README.md" in files and "docs/releases.md" in files
    assert check.scan(files) == []


def test_the_public_export_runs_the_check() -> None:
    text = (REPO / "scripts/publish-public.sh").read_text()
    assert 'scripts/release-private-paths.py" --tree "$TREE"' in text
