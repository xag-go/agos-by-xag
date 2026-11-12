"""Typed errors of every Hermes call (ADR 0024).

`EngineError` is the engine's one error type (re-exported by engine/hermes.py); the
gateway's subclasses keep it, so every `except EngineError` keeps working, and add
a `code` the API and the callers can tell apart."""

from __future__ import annotations

HERMES_FAILED = "HERMES_FAILED"
HERMES_TIMEOUT = "HERMES_TIMEOUT"
HERMES_UNAVAILABLE = "HERMES_UNAVAILABLE"
CAGE_REFUSED = "cage_refused"


class EngineError(RuntimeError):
    """The message is safe to show to the owner. `reason`: what Hermes itself said
    when it refused (refusal_line), "" when it said nothing AGOS may show. Callers
    that tell the owner why (actions/services/board/kanban_cli.py run) add it to their words."""

    code = "ENGINE_ERROR"

    def __init__(self, *args: object, reason: str = "") -> None:
        super().__init__(*args)
        self.reason = reason


class HermesFailed(EngineError):
    """Hermes ran and refused (a non-zero exit): Hermes is up."""

    code = HERMES_FAILED

    def __init__(self, *args: object, exit_code: int, reason: str = "") -> None:
        super().__init__(*args, reason=reason)
        self.exit_code = exit_code


class HermesTimeout(EngineError):
    """No answer in time (`started`), or the process could not start at all."""

    code = HERMES_TIMEOUT

    def __init__(self, *args: object, started: bool, reason: str = "") -> None:
        super().__init__(*args, reason=reason)
        self.started = started


class HermesUnavailable(EngineError, ConnectionError):
    """The root's circuit is open: nothing was started. Also a ConnectionError (an
    OSError), so code that treats "Hermes could not start" as no answer degrades
    the same way."""

    code = HERMES_UNAVAILABLE

    def __init__(self, root: str) -> None:
        EngineError.__init__(
            self, "The engine isn't answering right now; AGOS tries again shortly."
        )
        self.root = root


class CageRefused(EngineError):
    """The gateways' cage (engine/cage.py) is required and can't be built here, so
    nothing was started: the owner fixes bwrap (`agos doctor` says how) or sets
    AGOS_SANDBOXD=off on purpose. Not Hermes's fault, and not a retry case."""

    code = CAGE_REFUSED
