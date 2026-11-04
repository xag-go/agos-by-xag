"""How AGOS runs code in Hermes's runtime: the environment every Hermes child process gets
(RUNTIME, with_runtime, child_env) and the module whose runtime command AGOS asks Hermes
for and reuses (the goal judge's: JUDGE_MODULE, JUDGE_RUN).

Owns: RUNTIME, the one dict the engine fills at start.
Must not: start a process itself, or import another part of this package.

Part of engine/hermes (moved out of the old common.py).
"""

from __future__ import annotations

import os

__all__ = [
    "JUDGE_MODULE",
    "JUDGE_RUN",
    "RUNTIME",
    "child_env",
    "with_runtime",
]


# The Hermes install's own runtime (EngineConfig.runtime_dir), set when the engine
# starts: every Hermes process AGOS runs gets it, whichever code path starts it.
RUNTIME: dict[str, str] = {}


def with_runtime(env: dict[str, str]) -> dict[str, str]:
    """`env` plus HERMES_RUNTIME_DIR: without it a home outside ~/.hermes builds a
    runtime of its own and rewrites the install's shared launcher."""
    return {**RUNTIME, **env}


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for `hermes`/`docker`: agos-core's own variables never leak in
    (AGOS_*, test runners), and no Hermes session/gateway markers from whatever
    started agos-core (HERMES_*, _HERMES_*): with those, `hermes gateway stop`
    believed agos-core was part of a gateway and sent it SIGTERM."""
    drop = ("AGOS_", "PYTEST_", "HERMES", "_HERMES", "TERMINAL_")
    env = {k: v for k, v in os.environ.items() if not k.startswith(drop)}
    return {**env, **RUNTIME, **(extra or {})}


JUDGE_MODULE = "agos_goal_judge"

JUDGE_RUN = f"runpy.run_module('{JUDGE_MODULE}', run_name='__main__', alter_sys=True)"
