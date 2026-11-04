"""Hermes's managed scope (HERMES_MANAGED_DIR): the environment every Hermes command
gets, the managed config.yaml AGOS writes, the managed keys, and the commands run
without it.

Owns: The one value per install that every workspace shares, and its writer.

Must not: Write one workspace's own config (commands.py) or read a profile's settings
(env.py).

Part of engine/hermes (HermesEngine binds these functions as its methods).
"""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agos_core.engine.hermes.home_lock import home_write_lock
from agos_core.engine.hermes.managed_scope import MANAGED_ENV, MANAGED_FIRST_TIMEOUT_S, MANAGED_LOCK
from agos_core.engine.loop_guard import off_loop
from agos_core.hermes_gateway.errors import EngineError

if TYPE_CHECKING:
    from agos_core.engine.hermes import HermesEngine

__all__ = [
    "_MANAGED_KEYS",
    "_env",
    "_unmanaged",
    "gateway_managed",
    "managed_config",
    "managed_keys",
    "managed_write",
    "unmanaged_hermes",
    "unmanaged_in",
    "unmanaged_writes",
]


# Run in Hermes's runtime by managed_keys, with the managed folder as HERMES_HOME
# and no scope (Hermes refuses to write a name its scope pins: hermes_cli/config.py
# env_write_refusal): the extra keys of a provider as numbered lines <BASE>_2,
# <BASE>_3... of the managed .env, written by Hermes's own .env writer
# (save_env_value / remove_env_value). Hermes reads them in every home
# (agent/credential_pool.py _env_key_var_candidates: <BASE>_2 upward until the first
# missing one, so the numbers stay contiguous). Keys only on stdin; names out.
_MANAGED_KEYS = r"""
import json, logging, re
logging.disable(logging.CRITICAL)
from hermes_cli.config import load_env, save_env_value, remove_env_value
job = json.loads(@JOB@)
NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,80}$")
def numbered(base):
    have, n = [], 2
    while load_env().get("%s_%d" % (base, n), "").strip():
        have.append(n)
        n += 1
    return have
out = {}
try:
    base = job["base"]
    assert NAME.match(base), "bad name"
    if job["do"] == "add":
        env = load_env()
        same = next(("%s_%d" % (base, n) for n in numbered(base)
                     if env.get("%s_%d" % (base, n), "").strip() == job["key"]), None)
        have = numbered(base)
        end = len(have) + 2
        at = int(job.get("at") or end)
        at = at if 2 <= at <= end else end
        name = same or "%s_%d" % (base, at)
        if not same:
            # Back at its old number (an Undo): the later keys move down one.
            for n in range(end - 1, at - 1, -1):
                save_env_value("%s_%d" % (base, n + 1), load_env()["%s_%d" % (base, n)])
            save_env_value(name, job["key"])
        out["name"] = name
    elif job["do"] == "remove":
        have = numbered(base)
        k = int(job["n"])
        if k in have:
            for n in range(k, have[-1]):
                save_env_value("%s_%d" % (base, n), load_env()["%s_%d" % (base, n + 1)])
            remove_env_value("%s_%d" % (base, have[-1]))
    elif job["do"] == "swap":
        a, b = ("%s_%d" % (base, int(n)) for n in job["n"])
        env = load_env()
        if env.get(a, "").strip() and env.get(b, "").strip():
            first, second = env[a], env[b]
            save_env_value(a, second)
            save_env_value(b, first)
    out["names"] = sorted(n for n in load_env() if n.startswith(base + "_"))
except Exception as error:
    out = {"error": "%s: %s" % (type(error).__name__, error)}
print("AGOS-KEYS " + json.dumps(out))
"""


def managed_keys(self: "HermesEngine", job: dict[str, Any]) -> dict[str, Any]:
    """A provider's extra keys as numbered lines of the managed .env, by Hermes's
    own .env writer: {"do": "add", "base", "key", "at"?} | {"do": "remove", "base", "n"}
    | {"do": "swap", "base", "n": [i, j]}. The key travels on stdin only."""
    folder = self.settings.managed_home
    script = _MANAGED_KEYS.replace("@JOB@", repr(json.dumps(job)))
    with MANAGED_LOCK, home_write_lock(self.settings.managed_home):
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        first = not (folder / "config.yaml").is_file() and not (folder / ".env").is_file()
        found: dict[str, Any] = json.loads(
            self._in_runtime(
                folder,
                script,
                "AGOS-KEYS",
                timeout=MANAGED_FIRST_TIMEOUT_S if first else 120,
                extra=self._unmanaged(),
            )
        )
    if found.get("error"):
        raise EngineError(str(found["error"])[:300])
    return found


def _env(self: "HermesEngine") -> dict[str, str]:
    env = {"HOME": str(self.settings.host_home)}
    if self.settings.runtime_dir is not None:
        # Never let a root outside ~/.hermes pick a runtime of its own: Hermes
        # would install one there and rewrite the install's shared launcher.
        env["HERMES_RUNTIME_DIR"] = str(self.settings.runtime_dir)
    # The settings that are one value for every workspace (Hermes's Managed
    # Scope, actions/hermes_managed.py).
    env[MANAGED_ENV] = str(self.settings.managed_home)
    return env


# ---- Hermes's Managed Scope: one value for every workspace -------------


def _unmanaged(self: "HermesEngine") -> dict[str, str]:
    """HERMES_MANAGED_DIR pointing nowhere: Hermes then reads no managed scope
    (hermes_cli/managed_scope.py get_managed_dir: an override that isn't a
    folder is no scope, and it never falls back to /etc/hermes then)."""
    return {MANAGED_ENV: str(self.settings.managed_home / ".off")}


def managed_config(self: "HermesEngine") -> dict[str, Any]:
    """The managed config.yaml as Hermes reads it (every key pinned there)."""
    from agos_core.engine import config_file

    return config_file.read(self.settings.managed_home)


def managed_write(self: "HermesEngine", sets: list[tuple[str, str]], unsets: list[str]) -> None:
    """Hermes's own `hermes config set/unset` writes the managed config.yaml: run
    with the managed folder as its home and no scope (Hermes refuses to set a
    key its scope pins). Hermes writes the file whole through its config writer
    (a fresh file: a Hermes process never reads half of it); the scope reads
    only config.yaml and .env there (managed_scope.py load_managed_config /
    load_managed_env), and `config set` of a config key writes no .env."""
    if not sets and not unsets:
        return
    off_loop("hermes config (managed)")
    folder = self.settings.managed_home
    with MANAGED_LOCK, home_write_lock(self.settings.managed_home):
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        env = {**self._env(), **self._unmanaged(), "HERMES_HOME": str(folder)}
        # The folder's first Hermes command runs Hermes's one-time home upkeep
        # there (its dependency env: minutes on a busy machine, found live), so
        # the first call may take long; later ones are quick.
        first = not (folder / "config.yaml").is_file()
        if not first:
            # Every set and unset in one Hermes process (Hermes's own writer,
            # config_writes), one CLI each when that can't run.
            self._config_writes(
                folder,
                [
                    *(("config", "set", "--force", key, value) for key, value in sets),
                    *(("config", "unset", key) for key in unsets),
                ],
                self._unmanaged(),
                lambda command: self.runner.run(
                    [self.settings.hermes_bin, *command], timeout=120, env=env
                ),
            )
            return
        for key, value in sets:
            self.runner.run(
                [self.settings.hermes_bin, "config", "set", "--force", key, value],
                timeout=MANAGED_FIRST_TIMEOUT_S if first else 120,
                env=env,
            )
            first = False
        for key in unsets:
            self.runner.run(
                [self.settings.hermes_bin, "config", "unset", key], timeout=120, env=env
            )


def unmanaged_hermes(
    self: "HermesEngine", workspace_id: str, *args: str, timeout: float = 60
) -> str:
    """Hermes's CLI in a profile's home WITHOUT the managed scope: only to keep
    (or remove) a profile's own copy of a managed key, which Hermes refuses
    while the scope pins it (hermes_cli/config.py _exit_if_key_managed)."""
    off_loop(" ".join(["hermes", *args[:1]]))
    with home_write_lock(self.profile_home(workspace_id)):
        return self.runner.run(
            [self.settings.hermes_bin, *args],
            timeout=timeout,
            env={**self.hermes_env(workspace_id), **self._unmanaged()},
        )


def unmanaged_writes(
    self: "HermesEngine", workspace_id: str, commands: Sequence[Sequence[str]]
) -> list[str]:
    """unmanaged_hermes's `config set/unset` commands for one profile in ONE
    Hermes process (config_writes, with the scope off)."""
    return self._config_writes(
        self.profile_home(workspace_id),
        commands,
        {**self._unmanaged(), "HERMES_GATEWAY_LOCK_DIR": str(self.lock_dir(workspace_id))},
        lambda command: self.unmanaged_hermes(workspace_id, *command),
    )


def unmanaged_in(self: "HermesEngine", home: Path, *args: str, timeout: float = 60) -> str:
    """The same in any Hermes home (the shared one)."""
    off_loop(" ".join(["hermes", *args[:1]]))
    with home_write_lock(home):
        return self.runner.run(
            [self.settings.hermes_bin, *args],
            timeout=timeout,
            env={**self._env(), **self._unmanaged(), "HERMES_HOME": str(home)},
        )


def gateway_managed(self: "HermesEngine", workspace_id: str) -> bool | None:
    """Whether the root's running gateway reads the managed scope (its process
    was started with HERMES_MANAGED_DIR); None when no gateway runs."""
    home = self.profile_home(self.split(workspace_id)[0])
    if not self._gateway_up(home):
        return None
    try:
        pid = int(self.gateway_status(home).get("pid") or 0)
        entries = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    wanted = f"{MANAGED_ENV}={self.settings.managed_home}".encode()
    return wanted in entries
