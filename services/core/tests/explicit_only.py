"""Test folders that run only when named on the command line (tests/browser,
tests/load, tests/failure): they start a web build, a browser or real Hermes
gateways, so the core suite (`pytest` with no path, CI's core-tests job) leaves
them out. Each folder's conftest.py:

    pytest_ignore_collect = ignore_unless_asked(Path(__file__).parent)
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

__all__ = ["asked_for", "ignore_unless_asked"]


def asked_for(config: pytest.Config, folder: Path) -> bool:
    """`folder` (or a file in it) is one of the paths pytest was given."""
    for arg in config.args:
        path = Path(str(arg).split("::", 1)[0])
        if not path.is_absolute():
            path = Path(config.invocation_params.dir) / path
        try:
            path.resolve().relative_to(folder.resolve())
        except ValueError:
            continue
        return True
    return False


def ignore_unless_asked(folder: Path) -> Callable[[Path, pytest.Config], bool | None]:
    def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
        if collection_path.resolve() != folder.resolve() and not asked_for(config, folder):
            return True
        return None

    return pytest_ignore_collect
