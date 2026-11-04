"""Load tests run only when named (`pytest tests/load`): real Hermes gateways, one per
workspace (real_rig.py). Not in GitHub CI; locally or on the nightly runner."""

from __future__ import annotations

from pathlib import Path

from explicit_only import ignore_unless_asked

pytest_ignore_collect = ignore_unless_asked(Path(__file__).resolve().parent)
