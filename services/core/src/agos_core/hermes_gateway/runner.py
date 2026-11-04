"""The Runner every Hermes (and docker) command of the engine goes through, and the
gateway's policies around it (ADR 0024).

`Runner` is the protocol tests replace (59 files hand the engine a fake);
`SubprocessRunner` is the real one; `GatewayRunner` wraps either with the circuit
breaker per root, one retry for pure reads whose process could not start, and one
log record per call."""

from __future__ import annotations

import logging
import re
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

from agos_core.engine.loop_guard import off_loop
from agos_core.engine.waits import hermes_wait
from agos_core.hermes_gateway import breaker, policy
from agos_core.hermes_gateway.errors import (
    EngineError,
    HermesFailed,
    HermesTimeout,
    HermesUnavailable,
)

log = logging.getLogger("agos.engine")
calls_log = logging.getLogger("agos.hermes_gateway")

RETRY_PAUSE_S = 0.5


def _redacted(*texts: str) -> list[str]:
    """A failed Hermes command's output for the log, secrets hidden by Hermes's own
    masking (agent/redact.py redact_sensitive_text, engine/hermes_redact.py; when
    Hermes can't answer nothing of it is shown)."""
    from agos_core.engine import hermes_redact

    return hermes_redact.mask_many(list(texts))


# A path in a Hermes message: an absolute or home path of two parts or more.
_PART = r"[^\s/'\"`:,;()<>\[\]]+"
_PATH = re.compile(rf"(?<![\w~./-])(?:~|/{_PART})(?:/{_PART})+")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def refusal_line(err: str, out: str) -> str:
    """Hermes's own reason for a refused command, for the owner: the last line it
    printed on stderr (its CLI's errors: hermes_cli/kanban_output.py _err), else on
    stdout (its rich console's "Error: …"). The texts come already masked by
    Hermes's own masking (_redacted); each path is cut to its last part (where
    Hermes keeps its files can name the machine's accounts), at most 300
    characters. "" when Hermes said nothing, or its masking couldn't check it."""
    from agos_core.engine import hermes_redact

    for text in (err, out):
        lines = [line.strip() for line in _ANSI.sub("", text or "").splitlines() if line.strip()]
        if not lines:
            continue
        if hermes_redact.HIDDEN in text:
            return ""
        return _PATH.sub(lambda m: m.group(0).rsplit("/", 1)[-1], lines[-1])[:300]
    return ""


class Runner(Protocol):
    def run(self, args: Sequence[str], *, timeout: float, env: dict[str, str] | None = None) -> str:
        """Runs a command, returns stdout; raises EngineError on failure."""

    def spawn(
        self, args: Sequence[str], *, log_file: Path, env: dict[str, str] | None = None
    ) -> None:
        """Starts a long-running process, detached from agos-core."""


def _child_env(env: dict[str, str] | None) -> dict[str, str]:
    from agos_core.engine.hermes import child_env

    return child_env(env)


class SubprocessRunner:
    def run(self, args: Sequence[str], *, timeout: float, env: dict[str, str] | None = None) -> str:
        off_loop(" ".join([Path(args[0]).name, *args[1:3]]) if args else "?")
        try:
            done = subprocess.run(  # noqa: S603 — fixed argv, no shell
                list(args),
                capture_output=True,
                text=True,
                timeout=hermes_wait(timeout),
                env=_child_env(env),
                check=False,
                # Own session: a Hermes command that signals its process group
                # (e.g. `gateway stop`) must never reach agos-core itself.
                start_new_session=True,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise HermesTimeout(
                f"{Path(args[0]).name} did not answer",
                started=isinstance(error, subprocess.TimeoutExpired),
            ) from error
        if done.returncode != 0:
            # The caller decides if it's a problem (it logs it then); here it's a detail.
            # Hermes's rich console prints its own "Error: …" on stdout: keep both tails.
            err, out = _redacted((done.stderr or "")[-500:], (done.stdout or "")[-500:])
            log.info("%s failed (%s): %s | %s", args[:3], done.returncode, err, out)
            raise HermesFailed(
                f"{Path(args[0]).name} failed",
                exit_code=done.returncode,
                reason=refusal_line(err, out),
            )
        return done.stdout

    def spawn(
        self, args: Sequence[str], *, log_file: Path, env: dict[str, str] | None = None
    ) -> None:
        log_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with log_file.open("ab") as out:
            subprocess.Popen(  # noqa: S603 — fixed argv, no shell
                list(args),
                stdout=out,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=_child_env(env),
                start_new_session=True,
            )


def record(
    args: Sequence[str],
    root: str,
    started: float,
    *,
    outcome: str,
    exit_code: int | None,
    attempts: int = 1,
) -> None:
    """One log record of a Hermes call: its words (no values), root, time, exit."""
    fields: dict[str, Any] = {
        "command": policy.shown(args),
        "root": Path(root).name if root != policy.SHARED else root,
        "duration_s": round(time.monotonic() - started, 3),
        "exit_code": exit_code,
        "outcome": outcome,
        "attempts": attempts,
    }
    level = {
        "ok": logging.DEBUG,
        "started": logging.DEBUG,
        "refused": logging.INFO,
        "error": logging.INFO,
    }.get(outcome, logging.WARNING)
    calls_log.log(
        level,
        "hermes call %(command)s in %(root)s: %(outcome)s (exit %(exit_code)s, %(duration_s)ss)",
        fields,
        extra={"hermes": fields},
    )


class GatewayRunner:
    """Any Runner with the gateway's policies. Attributes it doesn't have itself
    (a fake's recorded calls, its switches) are the wrapped runner's."""

    _OWN = frozenset({"inner", "run", "spawn"})
    inner: Runner

    def __init__(self, inner: Runner) -> None:
        object.__setattr__(self, "inner", inner)

    def __getattr__(self, name: str) -> Any:
        if name == "inner":  # not set yet (a copy being made)
            raise AttributeError(name)
        return getattr(self.inner, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in self._OWN:
            object.__setattr__(self, name, value)
        else:
            setattr(self.inner, name, value)

    def run(self, args: Sequence[str], *, timeout: float, env: dict[str, str] | None = None) -> str:
        if not policy.is_hermes(args, env):  # docker and the like: as they are
            return self.inner.run(args, timeout=timeout, env=env)
        root = policy.root_of(env)
        breakers = breaker.BREAKERS
        started = time.monotonic()
        if not policy.is_recovery(args) and not breakers.allow(root):
            record(args, root, started, outcome="unavailable", exit_code=None, attempts=0)
            raise HermesUnavailable(root)
        attempts = 0
        while True:
            attempts += 1
            try:
                out = self.inner.run(args, timeout=timeout, env=env)
            except HermesFailed as error:
                breakers.answered(root)
                record(args, root, started, outcome="refused", exit_code=error.exit_code)
                raise
            except HermesTimeout as error:
                if not error.started and attempts == 1 and policy.is_read(args):
                    time.sleep(RETRY_PAUSE_S)
                    continue
                breakers.failed(root)
                outcome = "timeout" if error.started else "not started"
                record(args, root, started, outcome=outcome, exit_code=None, attempts=attempts)
                raise
            except BaseException:
                breakers.released(root)
                record(args, root, started, outcome="error", exit_code=None, attempts=attempts)
                raise
            breakers.answered(root)
            record(args, root, started, outcome="ok", exit_code=0, attempts=attempts)
            return out

    def spawn(
        self, args: Sequence[str], *, log_file: Path, env: dict[str, str] | None = None
    ) -> None:
        self.inner.spawn(args, log_file=log_file, env=env)


def wrapped(runner: Runner) -> GatewayRunner:
    """`runner` under the gateway's policies (never wrapped twice)."""
    return runner if isinstance(runner, GatewayRunner) else GatewayRunner(runner)


__all__ = [
    "EngineError",
    "GatewayRunner",
    "Runner",
    "SubprocessRunner",
    "refusal_line",
    "wrapped",
]
