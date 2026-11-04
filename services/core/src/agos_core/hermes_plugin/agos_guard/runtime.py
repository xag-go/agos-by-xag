"""Where the guard runs inside Hermes.

Split out of agos_core.hermes_plugin.agos_guard (the guard's facade). Owns: Hermes's
plugin context (register), this profile's name, the Kanban card this worker runs, the plugin's sibling files however
Hermes loaded them, and the report of a Hermes internal that failed (contract.py,
told once; the caller's fail-closed answer never changes).

Must not: decide on a tool call.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

__all__ = [
    "_CTX",
    "_bridge_module",
    "_contract",
    "_current_card",
    "_guard",
    "_missing",
    "_own_profile",
    "_report",
    "_sibling",
]

_CTX: dict[str, Any] = {"ctx": None}  # Hermes's plugin context (register)


def _current_card() -> str:
    """The Kanban card this worker runs (Hermes's dispatcher sets it), or ''."""
    return os.environ.get("HERMES_KANBAN_TASK", "")


def _own_profile() -> str:
    try:
        from hermes_cli.profiles import get_active_profile_name  # type: ignore[import-not-found]

        return str(get_active_profile_name() or "")
    except Exception as error:  # noqa: BLE001 — not inside Hermes: no profile known
        _report("hermes_cli.profiles.get_active_profile_name", error)
        return os.environ.get("HERMES_PROFILE", "")


def _bridge_module() -> Any:
    """The AGOS bridge (bridge.py beside this file), however Hermes loaded us."""
    return _sibling("bridge")


def _contract() -> Any:
    """contract.py beside this file: a Hermes internal that failed, told once."""
    return _sibling("contract")


def _report(name: str, error: BaseException | str | None = None) -> None:
    """A Hermes internal failed: told once (contract.py). Never raises: the caller's
    fail-closed answer is never changed by the report."""
    try:
        _contract().broken(name, error)
    except Exception:  # noqa: BLE001
        logging.getLogger("agos_guard").error("Hermes contract broken: %s", name)


def _missing(name: str, value: Any) -> Any:
    try:
        _contract().missing(name, value)
    except Exception:
        logging.getLogger("agos_guard").debug("contract report failed", exc_info=True)
    return value


def _guard(name: str) -> Any:
    """contextlib.suppress(Exception) around a Hermes internal, plus the report."""
    try:
        return _contract().guard(name)
    except Exception:  # noqa: BLE001
        import contextlib

        return contextlib.suppress(Exception)


def _sibling(stem: str) -> Any:
    """A module beside this file, however Hermes loaded us."""
    import importlib
    import importlib.util
    import sys

    try:
        return importlib.import_module(f"{__package__}.{stem}")
    except ImportError:
        name = f"agos_guard_{stem}"
        if name not in sys.modules:
            spec = importlib.util.spec_from_file_location(
                name, Path(__file__).parent / (stem + ".py")
            )
            if spec is None or spec.loader is None:
                raise
            sys.modules[name] = module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        return sys.modules[name]
