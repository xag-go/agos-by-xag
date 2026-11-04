"""Autouse fixtures every test gets (imported by conftest.py): Hermes never on the
core's event loop, and every Hermes Gateway circuit closed (ADR 0024)."""

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _hermes_never_on_the_loop() -> Iterator[None]:
    """Also when the code under test swallowed the guard's error (a broad except)."""
    from agos_core.engine import loop_guard

    loop_guard.broken.clear()
    yield
    found = list(loop_guard.broken)
    loop_guard.broken.clear()
    assert found == [], f"Hermes started on the core's event loop: {found}"


@pytest.fixture(autouse=True)
def _hermes_circuits_closed() -> Iterator[None]:
    """Each test starts with every root's circuit closed (hermes_gateway/breaker.py
    keeps one registry per process)."""
    from agos_core.hermes_gateway import breaker

    breaker.BREAKERS.reset()
    yield
    breaker.BREAKERS.reset()
