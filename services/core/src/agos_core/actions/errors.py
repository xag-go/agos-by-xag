"""Errors whose message is safe to show to the owner."""

from agos_core.domain.errors import ErrorCode, code_for_status
from agos_core.hermes_gateway.breaker import OPEN_FOR_S
from agos_core.hermes_gateway.errors import CageRefused, HermesTimeout, HermesUnavailable

# Hermes down or too slow (ADR 0024): the API answers 503 with the error's code
# (HERMES_UNAVAILABLE / HERMES_TIMEOUT) instead of an internal error.
HERMES_DOWN = (HermesUnavailable, HermesTimeout)
HERMES_RETRY_AFTER = str(int(OPEN_FOR_S))  # when the open circuit is tried again
# The gateways' cage can't be built here (engine/cage.py): 503 with code
# cage_refused and its fix, not an internal error (nothing AGOS can retry).
CAGE_DOWN = (CageRefused,)


class ActionError(Exception):
    """`code`: the typed code of the API's error body (domain/errors.py); by
    default the one of its status."""

    def __init__(self, message: str, status: int = 400, code: ErrorCode | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code or code_for_status(status)


class NotFoundError(ActionError):
    def __init__(self, what: str) -> None:
        super().__init__(f"{what} no longer exists.", 404)
