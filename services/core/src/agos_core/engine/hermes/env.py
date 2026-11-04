"""Each profile's settings as Hermes reads them: its config with the managed scope on
top, which .env names its gateway's two sides use, the secrets it holds, and
Hermes's config schema.

Owns: The read-only probes run in Hermes's runtime for these answers, their caches and
the bound on concurrent settings runs.

Must not: Write any setting (commands.py, managed.py). env_in_use stays in the facade: it
calls _side_by_side, which tests replace on engine/hermes.

Part of engine/hermes (HermesEngine binds these functions as its methods).
"""

import copy
import json
import logging
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agos_core.engine import hermes_contract, read_cache
from agos_core.engine.hermes.managed_scope import managed_files
from agos_core.engine.hermes.probe_runs import HERMES_SETTING_UP
from agos_core.engine.hermes.runtime_env import JUDGE_RUN, child_env
from agos_core.engine.loop_guard import off_loop
from agos_core.engine.waits import hermes_wait
from agos_core.hermes_gateway.errors import EngineError

log = logging.getLogger("agos.engine")

if TYPE_CHECKING:
    from agos_core.engine.hermes import HermesEngine

__all__ = [
    "_AS_READ",
    "_ENV_IN_USE",
    "_as_read",
    "_env_gateway",
    "_env_run",
    "_env_yaml_side",
    "_read_schema",
    "_side_by_side",
    "as_hermes_reads",
    "config_schema",
    "hermes_secrets",
]


def _side_by_side(
    first: Callable[[], dict[str, Any]], second: Callable[[], dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Both asks at once: `first` on a helper thread (Linux gives it this thread's
    priority, and its Hermes process too: a background ask stays in the
    background), `second` here. Either one's error is raised once both are done."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = first()
        except BaseException as error:  # noqa: BLE001 - raised below, on the caller's thread
            box["error"] = error

    helper = threading.Thread(target=run, name="agos-hermes-ask", daemon=True)
    helper.start()
    try:
        here = second()
    finally:
        helper.join()
    if "error" in box:
        raise box["error"]
    value: dict[str, Any] = box["value"]
    return value, here


# Run in Hermes's runtime by as_hermes_reads: each profile's own config.yaml with
# Hermes's managed scope on top, merged by Hermes itself
# (hermes_cli/managed_scope.py apply_managed_overlay: hermes_cli/config.py
# _deep_merge leaf by leaf, None never replaces a mapping, ${VAR} expanded in the
# managed values, a bare `model:` string promoted). The profile's own values stay as
# written (no defaults, no ${VAR} expansion of the profile's file).
_AS_READ = r"""
import json, logging
logging.disable(logging.CRITICAL)
from pathlib import Path
from utils import fast_safe_load
from hermes_cli.managed_scope import apply_managed_overlay
from hermes_cli.config import redact_config_value
def hidden(given, shown, path, found):
    # Where Hermes's own masker (redact_config_value: the one it runs before
    # printing any config) changed a value: that path holds a secret.
    if isinstance(given, dict) and isinstance(shown, dict):
        for k, v in given.items():
            hidden(v, shown.get(k), path + [str(k)], found)
    elif isinstance(given, list) and isinstance(shown, list):
        for i, v in enumerate(given):
            hidden(v, shown[i] if i < len(shown) else None, path + [i], found)
    elif given != shown and path not in found:
        found.append(path)
out, secret = {}, {}
for home in json.loads(@JOB@):
    try:
        with open(Path(home) / "config.yaml", encoding="utf-8-sig") as f:
            raw = fast_safe_load(f) or {}
    except Exception:
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    merged = apply_managed_overlay(raw)
    found = []
    hidden(raw, redact_config_value(raw), [], found)
    hidden(merged, redact_config_value(merged), [], found)
    out[home], secret[home] = merged, found
print("AGOS-ASREAD " + json.dumps({"configs": out, "secret": secret}, default=str))
"""


# Run in Hermes's runtime by env_in_use: what Hermes's gateway really has in its
# environment once it started in this home. Importing gateway.run is Hermes's own
# start (its .env, then config.yaml bridged into the environment: gateway/run.py
# _bridge_config_to_env), and load_gateway_config runs each platform's own YAML
# bridge (gateway/config.py :839; Telegram: plugins/platforms/telegram/adapter.py
# _apply_yaml_config, whose yaml_env_setter lets an explicit env value win,
# gateway/platforms/_shared.py :151). The gateway's unit carries HERMES_MANAGED_DIR
# (the drop-in), so the probe keeps it: Hermes applies the managed .env last with
# override (hermes_cli/env_loader.py _apply_managed_env) and overlays the managed
# config.yaml (hermes_cli/config.py _merge_managed_overlay). `diff`: only what the
# start set (a copy of the home holding config.yaml alone, with a scope holding only
# the managed config.yaml: the YAML side); else the gateway's side: the value of each
# .env name, the names the managed .env pins (Hermes's own load_managed_env), and
# every UPPER name the start left in the environment (the only names the YAML side
# reports), so both runs start at once and AGOS keeps the names the YAML side found.
# The YAML side's copy (`home`, `scope`) is NOT the process's HERMES_HOME: a Hermes
# process started in a brand-new home treats it as a data root of its own
# (hermes_constants.get_default_hermes_root) and its launch first builds a whole
# dependency environment there (hermes_cli/venv_sync.py prepare_launch →
# _prepare_borrowed_launch: `uv venv`, `uv sync`; ~400 MB and ~50 s calm, minutes
# when busy, on every probe). The process starts in the profile's own home instead
# (its root's environment is the one its gateway runs on), and Hermes's start is
# pointed at the copy inside the process: Hermes reads HERMES_HOME and
# HERMES_MANAGED_DIR when it is asked (hermes_constants.get_process_hermes_home,
# hermes_cli/managed_scope.py get_managed_dir). A Hermes that bound them earlier
# fails the probe (checked below) rather than report the profile's .env as YAML.
_ENV_IN_USE = r"""
import json, logging, os
logging.disable(logging.CRITICAL)
job = json.loads(@JOB@)
# The gateway's own process environment (its service unit): nothing of the caller's
# shell may stand in for a .env or config.yaml value.
for name in list(os.environ):
    if not (name in ("PATH", "HOME", "USER", "LOGNAME", "LANG", "TMPDIR", "SHELL")
            or name.startswith(("LC_", "XDG_", "HERMES_HOME", "HERMES_RUNTIME",
                                "HERMES_MANAGED_DIR"))):
        del os.environ[name]
if job.get("home"):
    os.environ["HERMES_HOME"] = job["home"]
    os.environ["HERMES_MANAGED_DIR"] = job["scope"]
start = dict(os.environ)
import gateway.run
from gateway.config import load_gateway_config
try:
    load_gateway_config()
except Exception:
    pass
if job.get("home"):
    from hermes_constants import get_hermes_home
    from hermes_cli.managed_scope import get_managed_dir
    read = (os.path.realpath(str(get_hermes_home())), os.path.realpath(str(get_managed_dir())))
    if read != (os.path.realpath(job["home"]), os.path.realpath(job["scope"])):
        raise SystemExit("Hermes did not read the copy of config.yaml: %r" % (read,))
if job.get("diff"):
    out = {k: v for k, v in os.environ.items() if k.isupper() and start.get(k) != v}
else:
    from hermes_cli.config import load_env
    from hermes_cli.managed_scope import load_managed_env
    pinned = set(load_managed_env())
    names = set(load_env()) | pinned
    out = {"used": {k: os.environ.get(k) for k in sorted(names)}, "managed": sorted(pinned),
           "env": {k: v for k, v in os.environ.items() if k.isupper()}}
print("AGOS-ENVUSE " + json.dumps(out))
"""


def as_hermes_reads(self: "HermesEngine", homes: list[Path]) -> dict[str, dict[str, Any]]:
    """Each home's config.yaml with Hermes's managed scope on top, merged by
    Hermes's own `apply_managed_overlay` (one run for every home): {home: config}.
    Kept while those files and the managed config.yaml are unchanged."""
    found: dict[str, dict[str, Any]] = self._as_read(homes)["configs"]
    return found


def hermes_secrets(self: "HermesEngine", homes: list[Path]) -> dict[str, list[list[str | int]]]:
    """Per home, the paths of the values Hermes itself masks before it prints a
    config (hermes_cli/config.py redact_config_value: its credential key names,
    `headers.Authorization` / `X-API-Key`, an env map's `*_KEY`, a `${VAR}`
    reference left visible), in the home's own file and in Hermes's read of it.
    The same run (and cache) as as_hermes_reads."""
    found: dict[str, list[list[str | int]]] = self._as_read(homes)["secret"]
    return found


def _as_read(self: "HermesEngine", homes: list[Path]) -> dict[str, Any]:
    wanted = tuple(str(home) for home in homes)
    reads_now = read_cache.content_stamp(
        *(home / "config.yaml" for home in homes),
        managed_files(self.settings.managed_home)[0],
    )

    def ask() -> dict[str, Any]:
        script = _AS_READ.replace("@JOB@", repr(json.dumps(list(wanted))))
        # The script reads each home's file by its path (read only); it runs in the
        # shared home.
        with self._settings_slots:
            found: dict[str, Any] = json.loads(
                self._in_runtime(self.settings.hermes_home, script, "AGOS-ASREAD")
            )
        return found

    return copy.deepcopy(self._as_reads.get(wanted, reads_now, ask))


def _env_yaml_side(self: "HermesEngine", home: Path) -> dict[str, Any]:
    import tempfile

    from agos_core.engine.env_probe import yaml_only_home

    with tempfile.TemporaryDirectory(prefix="agos-env-") as scratch:
        yaml_home, yaml_scope = yaml_only_home(home, self.settings.managed_home, Path(scratch))
        # Started in the profile's own home (never a fresh one: see _ENV_IN_USE);
        # Hermes's start is pointed at the copy inside the process.
        job = {"diff": True, "home": str(yaml_home), "scope": str(yaml_scope)}
        return self._env_run(home, job)


def _env_gateway(self: "HermesEngine", home: Path) -> dict[str, Any]:
    return self._env_run(home, {})


def _env_run(self: "HermesEngine", home: Path, job: dict[str, Any]) -> dict[str, Any]:
    """One of the probe's two Hermes runs, in the profile's own home, holding one
    of the settings slots while it runs. Refused because the home's root is
    being set up by another start (HERMES_SETTING_UP: the probe's other run, in
    a brand-new root), it asks once more after the probe runs running then have
    ended (_ProbeRuns), so the page gets Hermes's answer. Any other error, and a
    second refusal, is raised as Hermes gave it."""
    script = _ENV_IN_USE.replace("@JOB@", repr(json.dumps(job)))
    try:
        with self._settings_slots, self._probe_runs.running():
            found: dict[str, Any] = json.loads(self._in_runtime(home, script, "AGOS-ENVUSE"))
        return found
    except EngineError as error:
        if HERMES_SETTING_UP not in str(error):
            raise
        log.info("Hermes is setting up the root of %s: asked again after the other run", home)
    with self._probe_runs.after_the_others(), self._settings_slots, self._probe_runs.running():
        found = json.loads(self._in_runtime(home, script, "AGOS-ENVUSE"))
    return found


def config_schema(self: "HermesEngine") -> list[Any]:
    """Hermes's own list of its settings (its dashboard's schema and defaults,
    with the descriptions of its defaults file), read in Hermes's runtime and
    kept while that file is unchanged (engine/hermes_schema.py)."""
    from agos_core.engine import hermes_schema

    seen = hermes_schema.cached()
    if seen is not None:
        return seen
    # One ask at a time: a page and the read-ahead asking together start Hermes
    # once (the second finds the first's answer kept).
    with self._schema_lock:
        seen = hermes_schema.cached()
        if seen is not None:
            return seen
        failed = self._schema_failed
        if failed is not None and time.monotonic() - failed[0] < 60:
            raise EngineError(failed[1])  # asked a moment ago: not again at once
        try:
            return self._read_schema()
        except EngineError as error:
            self._schema_failed = (time.monotonic(), str(error))
            raise


def _read_schema(self: "HermesEngine") -> list[Any]:
    from agos_core.engine import hermes_schema

    argv = list(self._runtime_argv())
    argv[-1] = argv[-1].replace(JUDGE_RUN, "exec(sys.stdin.read())")
    env = child_env({**self._env(), "HERMES_HOME": str(self.settings.hermes_home)})
    off_loop("hermes settings schema")
    done = subprocess.run(  # noqa: S603 - Hermes's own launcher, fixed argv
        argv,
        input=hermes_schema.SCRIPT,
        capture_output=True,
        text=True,
        timeout=hermes_wait(120),
        env=env,
        check=False,
        start_new_session=True,
    )
    hermes_contract.ran(done)
    try:
        if done.returncode != 0:
            raise ValueError(done.stderr[-300:])
        fields, source = hermes_schema.parse(done.stdout)
    except ValueError as error:
        raise EngineError(f"Hermes's settings list not read: {error}") from error
    hermes_schema.keep(source, fields)
    self._schema_failed = None
    return fields
