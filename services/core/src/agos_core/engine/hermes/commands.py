"""The Hermes commands AGOS runs: the hermes CLI per workspace (one config writer per
home at a time), batched config writes, backups, and scripts run in Hermes's own
runtime (the goal judge's launcher).

Owns: The argv, environment and timeout of every `hermes` command and runtime script, and
the per-home write lock around config writes.

Must not: Decide which keys to write (apply in the facade, managed.py) or read Hermes's
settings (env.py).

Part of engine/hermes (HermesEngine binds these functions as its methods).
"""

import contextlib
import json
import logging
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agos_core.engine import hermes_contract
from agos_core.engine.hermes.home_lock import home_write_lock, writes_config
from agos_core.engine.hermes.runtime_env import JUDGE_MODULE, JUDGE_RUN, child_env
from agos_core.engine.loop_guard import off_loop
from agos_core.engine.waits import hermes_wait
from agos_core.hermes_gateway.errors import EngineError
from agos_core.hermes_gateway.runner import _redacted

log = logging.getLogger("agos.engine")

if TYPE_CHECKING:
    from agos_core.engine.hermes import HermesEngine

__all__ = [
    "_CONFIG_WRITES",
    "_cli",
    "_config_batch",
    "_config_writes",
    "_hermes",
    "_in_runtime",
    "_runtime_argv",
    "backup",
    "backup_root",
    "config_writes",
    "set_setting",
]


# Run in Hermes's runtime by config_writes: several `hermes config set --force` /
# `hermes config unset` commands in ONE Hermes process (each is ~0.65 s as its own
# CLI). It does what the CLI does around Hermes's writer: the .env load
# hermes_cli/main.py runs before any command, then per command
# hermes_cli/config.py _cmd_config_set / _cmd_config_unset -> _run_write_command(
# set_config_value | unset_config_value) (a refused key exits 1 there: managed-
# pinned, invalid, unreadable config); UPPER names go to Hermes's .env writer inside
# set_config_value itself. A set whose value the home already holds (the value as
# Hermes coerces it, _coerce_config_set_value, at the key Hermes writes, and its
# terminal .env mirror) is skipped: Hermes would write the same file. The first
# refused command stops the run, like the per-command loop it replaces.
_CONFIG_WRITES = r"""
import contextlib, io, json
from pathlib import Path
from hermes_cli._startup_fast import project_root_str
from hermes_cli.env_loader import load_hermes_dotenv
load_hermes_dotenv(project_env=Path(project_root_str()) / ".env")
from hermes_cli.config import (
    _MISSING, _coerce_config_set_value, _exit_if_key_managed, _get_nested,
    _is_env_config_key, _legacy_gateway_platforms_key, _redirect_platform_display_key,
    _run_write_command, _terminal_env_value, get_config_path, is_managed, load_env,
    require_readable_config_before_write, set_config_value,
    terminal_config_env_var_for_key, unset_config_value)
from hermes_cli.config_env_routing import is_env_setting_key
job = json.loads(@JOB@)
_ALWAYS = {"model", "display.skin", "display.language", "model.api_base", "api_base"}

def _same(key, value):
    if is_managed() or _is_env_config_key(key):
        return False
    raw = require_readable_config_before_write(get_config_path())
    if is_env_setting_key(key):
        held = load_env().get(key.upper())
        return held == value and key not in raw and key.upper() not in raw
    if (key in _ALWAYS or _legacy_gateway_platforms_key(key)
            or _redirect_platform_display_key(key)[0] != key
            or (key.lower().startswith("model.") and isinstance(raw.get("model"), str))):
        return False
    have = _get_nested(raw, key)
    if have is _MISSING:
        return False
    want = _coerce_config_set_value(key, value)
    if json.dumps(have, sort_keys=True, default=str) != json.dumps(want, sort_keys=True, default=str):
        return False
    mirror = terminal_config_env_var_for_key(key)
    return not mirror or key == "terminal.cwd" or load_env().get(mirror) == _terminal_env_value(want)

done, failed = [], None
for op in job:
    out, err = io.StringIO(), io.StringIO()
    wrote = True
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            if op[0] == "set":
                _exit_if_key_managed(op[1], "set")
                try:
                    wrote = not _same(op[1], op[2])
                except (Exception, SystemExit):
                    wrote = True
                if wrote:
                    _run_write_command(set_config_value, op[1], op[2], bool(op[3]))
            else:
                _run_write_command(unset_config_value, op[1])
    except SystemExit as exc:
        if exc.code not in (None, 0):
            said = (err.getvalue() or out.getvalue()).strip().splitlines() or ["refused"]
            failed = {"key": op[1], "code": exc.code, "said": said[-1][:300]}
            break
    except RuntimeError as exc:
        failed = {"key": op[1], "code": 1, "said": str(exc)[:300]}
        break
    done.append([op[1], wrote])
print("AGOS-SETS " + json.dumps({"done": done, "failed": failed}))
"""


def _in_runtime(
    self: "HermesEngine",
    home: Path,
    script: str,
    tag: str,
    *,
    timeout: float = 120,
    extra: dict[str, str] | None = None,
) -> str:
    """One script in Hermes's runtime with HERMES_HOME=home; its tagged line."""
    off_loop(f"Hermes runtime script {tag}")
    argv = list(self._runtime_argv())
    argv[-1] = argv[-1].replace(JUDGE_RUN, "exec(sys.stdin.read())")
    env = child_env({**self._env(), **(extra or {}), "HERMES_HOME": str(home)})
    try:
        done = subprocess.run(  # noqa: S603 - Hermes's own launcher, fixed argv
            argv,
            input=script,
            capture_output=True,
            text=True,
            timeout=hermes_wait(timeout),
            env=env,
            check=False,
            start_new_session=True,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise EngineError(f"Hermes didn't answer: {error}") from error
    hermes_contract.ran(done)
    lines = [ln for ln in done.stdout.splitlines() if ln.startswith(f"{tag} ")]
    if done.returncode != 0 or not lines:
        tail = done.stderr.strip().splitlines()[-1:] or ["no answer"]
        raise EngineError(f"Hermes didn't answer: {tail[0][:300]}")
    return lines[-1][len(tag) + 1 :]


def set_setting(self: "HermesEngine", workspace_id: str, key: str, value: str) -> None:
    """One setting of the profile's config (Hermes reads it when it needs it;
    nothing restarts)."""
    self._hermes(workspace_id, "config", "set", key, value)


def _cli(self: "HermesEngine", *args: str, timeout: float = 60) -> str:
    off_loop(" ".join(["hermes", *args[:1]]))
    return self.runner.run([self.settings.hermes_bin, *args], timeout=timeout, env=self._env())


def backup(self: "HermesEngine", output: Path, *, timeout: float = 1800) -> None:
    """Hermes's own backup of the shared home (General Settings' login and keys)
    as one zip; `hermes import` restores it. Each root has its own (backup_root)."""
    self._cli("backup", "--output", str(output), "--keep", "0", timeout=timeout)


def backup_root(
    self: "HermesEngine", workspace_id: str, output: Path, *, timeout: float = 1800
) -> None:
    """Hermes's own backup of a workspace's root (the Co-Founder, its members,
    memory, sessions, skills, cron); `hermes import` restores it."""
    off_loop("hermes backup")
    self.runner.run(
        [self.settings.hermes_bin, "backup", "--output", str(output), "--keep", "0"],
        timeout=timeout,
        env=self.hermes_env(self.split(workspace_id)[0]),
    )


def _hermes(self: "HermesEngine", workspace_id: str, *args: str, timeout: float = 60) -> str:
    """Hermes's CLI run IN this profile's home (never by name in another home)."""
    off_loop(" ".join(["hermes", *args[:1]]))
    lock = (
        home_write_lock(self.profile_home(workspace_id))
        if writes_config(args)
        else contextlib.nullcontext()
    )
    with lock:
        return self.runner.run(
            [self.settings.hermes_bin, *args],
            timeout=timeout,
            env=self.hermes_env(workspace_id),
        )


def config_writes(
    self: "HermesEngine", workspace_id: str, commands: Sequence[Sequence[str]]
) -> list[str]:
    """This profile's `hermes config set [--force] <key> <value>` / `hermes config
    unset <key>` commands, in their order, run by Hermes's own writer in ONE
    Hermes process under the home's write lock (_CONFIG_WRITES; each command as
    its own CLI is ~0.65 s). A set whose value the home already holds is
    skipped. A refused command raises like the CLI's (EngineError) and stops
    the rest. When the one process can't run, each command runs as its own
    CLI, as before. Returns the keys Hermes wrote."""
    return self._config_writes(
        self.profile_home(workspace_id),
        commands,
        {"HERMES_GATEWAY_LOCK_DIR": str(self.lock_dir(workspace_id))},
        lambda command: self._hermes(workspace_id, *command),
    )


def _config_writes(
    self: "HermesEngine",
    home: Path,
    commands: Sequence[Sequence[str]],
    extra: dict[str, str],
    one_by_one: Callable[[Sequence[str]], object],
    *,
    timeout: float = 120,
) -> list[str]:
    ops: list[list[Any]] = []
    for command in commands:
        args = [a for a in command[2:] if a != "--force"]
        if command[0] != "config" or command[1] not in ("set", "unset"):
            raise ValueError(f"not a Hermes config write: {command[:2]}")
        if command[1] == "set" and len(args) == 2:
            ops.append(["set", args[0], args[1], "--force" in command[2:]])
        elif command[1] == "unset" and len(args) == 1:
            ops.append(["unset", args[0]])
        else:
            raise ValueError(f"not a Hermes config write: {command[:2]}")
    if not ops:
        return []
    off_loop("hermes config writes")
    with home_write_lock(home):
        # A home Hermes hasn't made yet: its first command makes it (CLI).
        if (home / "config.yaml").is_file():
            script = _CONFIG_WRITES.replace("@JOB@", repr(json.dumps(ops)))
            try:
                answer = json.loads(self._config_batch(home, script, extra=extra, timeout=timeout))
                done = [str(key) for key, wrote in answer["done"] if wrote]
                failed = answer.get("failed")
            except (EngineError, ValueError, KeyError, TypeError) as error:
                log.info("Hermes's config writes in one process failed (%s): one by one", error)
            else:
                if failed:
                    (said,) = _redacted(str(failed.get("said") or ""))
                    log.info("hermes config %s failed: %s", failed.get("key"), said)
                    raise EngineError("hermes failed")
                return done
        for command in commands:
            one_by_one(command)
        return [op[1] for op in ops]


def _config_batch(
    self: "HermesEngine", home: Path, script: str, *, extra: dict[str, str], timeout: float
) -> str:
    """The one Hermes process of _config_writes (tests stand in for it)."""
    return self._in_runtime(home, script, "AGOS-SETS", timeout=timeout, extra=extra)


# ---- goal judge --------------------------------------------------------


def _runtime_argv(self: "HermesEngine") -> list[str]:
    """How Hermes runs a module in its own runtime (its documented launcher)."""
    if self._judge_argv is None:
        out = self._cli("--print-runtime-command", "--module", JUDGE_MODULE, timeout=30)
        try:
            argv = json.loads(out)
        except ValueError as error:
            raise EngineError("this Hermes did not say how it runs its modules") from error
        if not argv or JUDGE_RUN not in argv[-1]:
            raise EngineError("this Hermes can't run its goal judge for AGOS")
        self._judge_argv = argv
    return self._judge_argv
