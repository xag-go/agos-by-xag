"""Why the registry refuses a run (no HTTP status here: callers map them).

Owns: the registry's own refusals. Must not: carry a service's errors (those stay
the service's, e.g. ActionError, and pass through the registry unchanged).
"""

from __future__ import annotations

__all__ = ["OperationNotAllowed", "UnknownOperation"]


class UnknownOperation(LookupError):
    """No operation of that name is declared and bound."""


class OperationNotAllowed(PermissionError):
    """This caller may not run it (owner only, another workspace, done once)."""
