"""How long AGOS waits for a Hermes command or runtime script.

Each one starts a fresh Hermes runtime: seconds alone, far more on a busy machine (a
30 s check timed out while the same call took 14 s alone). No call AGOS makes to
Hermes waits less than HERMES_MIN_WAIT_S (owner rule: no short time limits); a
caller asking more keeps its own.
"""

HERMES_MIN_WAIT_S = 300.0


def hermes_wait(timeout: float) -> float:
    return max(float(timeout), HERMES_MIN_WAIT_S)
