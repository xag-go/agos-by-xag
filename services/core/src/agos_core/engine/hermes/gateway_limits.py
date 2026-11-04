"""How AGOS runs a Hermes gateway: where its API server listens, which supervisors may run
it, how long a restart lets running turns drain and how long a stop waits.

Must not: start, stop or read a gateway (gateway_run.py, gateway_unit.py, status.py).

Part of engine/hermes (moved out of the old common.py).
"""

from __future__ import annotations

__all__ = [
    "API_HOST",
    "RESTART_DRAIN_S",
    "STOP_HEADROOM_S",
    "STOP_WAIT_S",
    "SUPERVISORS",
]


API_HOST = "127.0.0.1"

# How long Hermes lets running answers finish when its gateway is stopped
# (agent.restart_drain_timeout): AGOS's start value for a new profile, then the
# owner's choice (engine/owner_choices.py). AGOS's own stop waits for Hermes's own
# stop budget from it (the quiet drain's answer, `_QUIET_DRAIN`) plus its own
# headroom; STOP_WAIT_S only when Hermes can't say.
RESTART_DRAIN_S = 60

STOP_HEADROOM_S = 30.0

STOP_WAIT_S = RESTART_DRAIN_S + 60

# How a root's gateway runs: Hermes's own systemd user service, or a process AGOS
# starts once (throwaway roots in tests and e2e runs; nothing restarts it).
SUPERVISORS = ("systemd", "spawn")
