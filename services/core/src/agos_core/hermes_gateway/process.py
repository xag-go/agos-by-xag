"""Runs of Hermes's runtime or CLI that don't go through the engine's Runner
(ADR 0024): a probe script in Hermes's Python, an interactive sign-in. Same circuit
breaker and log as the Runner; the caller keeps its own result handling (the exit
code, the raw TimeoutExpired / OSError it already catches; an open circuit raises
HermesUnavailable, which is an OSError too). The caller's timeout is used as is."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Sequence
from typing import Any

from agos_core.hermes_gateway import breaker, policy
from agos_core.hermes_gateway.errors import HermesUnavailable
from agos_core.hermes_gateway.runner import record

# What callers need from subprocess to talk to such a process (actions/ never
# imports subprocess itself: tests/test_hermes_gateway_ratchet.py).
PIPE = subprocess.PIPE
DEVNULL = subprocess.DEVNULL
Popen = subprocess.Popen
SubprocessError = subprocess.SubprocessError
TimeoutExpired = subprocess.TimeoutExpired


def run_process(
    argv: Sequence[str],
    *,
    timeout: float,
    env: dict[str, str] | None = None,
    input: str | None = None,
    cwd: str | None = None,
) -> subprocess.CompletedProcess[str]:
    root = policy.root_of(env)
    breakers = breaker.BREAKERS
    started = time.monotonic()
    if not breakers.allow(root):
        record(argv, root, started, outcome="unavailable", exit_code=None, attempts=0)
        raise HermesUnavailable(root)
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            list(argv),
            input=input,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=cwd,
            check=False,
        )
    except subprocess.TimeoutExpired:
        breakers.failed(root)
        record(argv, root, started, outcome="timeout", exit_code=None)
        raise
    except OSError:
        breakers.failed(root)
        record(argv, root, started, outcome="not started", exit_code=None)
        raise
    breakers.answered(root)
    outcome = "ok" if done.returncode == 0 else "refused"
    record(argv, root, started, outcome=outcome, exit_code=done.returncode)
    return done


def spawn_process(
    argv: Sequence[str], *, env: dict[str, str] | None, **popen: Any
) -> subprocess.Popen[str]:
    """A long-lived Hermes process the caller talks to (its pipes are the caller's)."""
    root = policy.root_of(env)
    started = time.monotonic()
    if not breaker.BREAKERS.allow(root):
        record(argv, root, started, outcome="unavailable", exit_code=None, attempts=0)
        raise HermesUnavailable(root)
    try:
        process: subprocess.Popen[str] = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            list(argv), env=env, **popen
        )
    except OSError:
        breaker.BREAKERS.failed(root)
        record(argv, root, started, outcome="not started", exit_code=None)
        raise
    breaker.BREAKERS.released(root)
    record(argv, root, started, outcome="started", exit_code=None)
    return process
