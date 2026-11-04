"""Schemathesis's check for AGOS: no 500 (used by tests/security/test_api_fuzz.py;
a hand run of Schemathesis's CLI loads it with SCHEMATHESIS_HOOKS=tests/security/fuzz_hooks.py).

A 500 is an exception no handler mapped. A 502/503 says Hermes or Docker isn't
answering, which is right on the fuzz rig (it has neither), so it is not a finding.
Schemathesis is imported lazily: it is not one of the core's dependencies (the nightly
adds it with `uv run --with`).
"""

from __future__ import annotations

import contextlib
import importlib
from typing import Any

__all__ = ["check", "no_unhandled_error"]


def no_unhandled_error(ctx: Any, response: Any, case: Any) -> bool | None:
    if response.status_code == 500:
        raise AssertionError(f"500 from {case.method} {case.path}: {response.text[:300]}")
    return None


_REGISTERED: list[Any] = []


def check() -> Any:
    """The check, registered with Schemathesis once."""
    if not _REGISTERED:
        schemathesis: Any = importlib.import_module("schemathesis")
        _REGISTERED.append(schemathesis.check(no_unhandled_error))
    return _REGISTERED[0]


with contextlib.suppress(ImportError):  # the CLI imports this module as its hooks
    check()
