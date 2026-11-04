"""Failure tests run only when named (`pytest tests/failure`): they start real Hermes
gateways on a throwaway rig (real_rig.py). Not in GitHub CI (no Hermes there): run
them locally or on the nightly self-hosted runner."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from explicit_only import ignore_unless_asked

from failure.real_rig import RealRig, add_workspace, real_rig

HERE = Path(__file__).resolve().parent

pytest_ignore_collect = ignore_unless_asked(HERE)


@pytest.fixture(scope="session")
def rig() -> Iterator[RealRig]:
    with real_rig("l6-failure", "9621,9622,9623") as real:
        add_workspace(real, "Alpha", members=("writer",))
        yield real


@pytest.fixture
def alpha(rig: RealRig) -> Iterator[dict[str, Any]]:
    """The workspace and its Co-Founder DM; after the test, nothing of the rig is
    left broken for the next one (core, model and gateway up, no live turn)."""
    ws = rig.workspaces["Alpha"]
    yield {"ws": ws, "chat": rig.dm(ws)}
    rig.wait("no live turn left", lambda: not rig.live_turns(), 240, 2)
