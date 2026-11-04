"""The Hermes Gateway (ADR 0024): the one place AGOS talks to Hermes.

It wraps calls and never does what Hermes does: typed errors (`errors`), a circuit
breaker per workspace root (`breaker`), bounded retry for pure reads and one log
record per call (`runner`), the CLI entry points actions use (`cli`), runs of
Hermes's runtime outside the Runner (`process`) and the read-only opens of
Hermes's own databases (`hermes_db`)."""

from agos_core.hermes_gateway.errors import (
    HERMES_FAILED,
    HERMES_TIMEOUT,
    HERMES_UNAVAILABLE,
    EngineError,
    HermesFailed,
    HermesTimeout,
    HermesUnavailable,
)

__all__ = [
    "HERMES_FAILED",
    "HERMES_TIMEOUT",
    "HERMES_UNAVAILABLE",
    "EngineError",
    "HermesFailed",
    "HermesTimeout",
    "HermesUnavailable",
]
