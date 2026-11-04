"""Hermes's CLI as actions call it (ADR 0024): the public names for the engine's
CLI entry points. Each forwards to the engine's own method, so its per-home write
lock, its environment (the root's HERMES_HOME, the managed scope) and the tests'
patches on the engine stay where they are; the policies run under it, in the
engine's runner (hermes_gateway/runner.py GatewayRunner)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agos_core.engine.hermes import HermesEngine


def cli(engine: HermesEngine, workspace_id: str, *args: str, timeout: float = 60) -> str:
    """`hermes <args>` IN this profile's home (never by name in another home)."""
    return engine._hermes(workspace_id, *args, timeout=timeout)


def walled_cli(engine: HermesEngine, key: str, *args: str, timeout: float = 60) -> str:
    """`hermes <args>` for this profile behind its wall (a plugin's CLI command)."""
    return engine.walled_cli(key, *args, timeout=timeout)


def config_writes(
    engine: HermesEngine, workspace_id: str, commands: Sequence[Sequence[str]]
) -> list[str]:
    """`hermes config set/unset` commands for one profile, in one Hermes process."""
    return engine.config_writes(workspace_id, commands)


def managed_write(engine: HermesEngine, sets: list[tuple[str, str]], unsets: list[str]) -> None:
    """Hermes's own `config set/unset` on the managed config.yaml (every workspace)."""
    engine.managed_write(sets, unsets)


def unmanaged_writes(
    engine: HermesEngine, workspace_id: str, commands: Sequence[Sequence[str]]
) -> list[str]:
    """config_writes with the managed scope off (a profile's own copy of a key)."""
    return engine.unmanaged_writes(workspace_id, commands)


def unmanaged_in(engine: HermesEngine, home: Path, *args: str, timeout: float = 60) -> str:
    """`hermes <args>` in any Hermes home with the managed scope off."""
    return engine.unmanaged_in(home, *args, timeout=timeout)
