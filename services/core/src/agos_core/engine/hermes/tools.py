"""A profile's tools as Hermes sees them: which are ready, the catalog, the tool
services and their credentials, the / command menu, and Hermes's own tool installs.

Owns: The scripts and CLI runs for tools, and their caches per home.

Must not: Turn toolsets on or off for the owner (actions/hermes_config.py) or write other
settings.

Part of engine/hermes (HermesEngine binds these functions as its methods).
"""

import contextlib
import json
import logging
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agos_core.engine import hermes_contract, read_cache
from agos_core.engine.hermes.home_lock import home_write_lock
from agos_core.engine.hermes.managed_scope import managed_files
from agos_core.engine.hermes.runtime_env import JUDGE_RUN, child_env
from agos_core.engine.loop_guard import off_loop
from agos_core.engine.waits import hermes_wait
from agos_core.hermes_gateway.errors import EngineError

log = logging.getLogger("agos.engine")

if TYPE_CHECKING:
    from agos_core.engine.hermes import HermesEngine

__all__ = [
    "SERVICE_TOOLSETS",
    "TOOLS_CHECK_TTL",
    "_COMMAND_MENU",
    "_CREDENTIALS",
    "_TOOLS_CATALOG",
    "_TOOL_ACTIVE",
    "_TOOL_CHECK",
    "_TOOL_SERVICE",
    "_check_tools",
    "_read_menu",
    "_tool_services_now",
    "command_menu",
    "forget_tools",
    "save_credentials",
    "set_tool_service",
    "tool_keys",
    "tool_readiness",
    "tool_services_in",
    "tools_catalog",
    "tools_install",
]


# Run in Hermes's runtime by tool_readiness: which toolsets Hermes really gives the
# model in this profile (each tool's own check: its service, credentials).
_TOOL_CHECK = r"""
import json, logging
logging.disable(logging.CRITICAL)
from toolsets import TOOLSETS
from model_tools import get_tool_definitions
out = {}
for ts in json.loads(@SETS@):
    want = set(TOOLSETS.get(ts, {}).get("tools", []))
    try:
        got = {d["function"]["name"] for d in get_tool_definitions(enabled_toolsets=[ts], quiet_mode=True)}
    except TypeError:
        got = {d["function"]["name"] for d in get_tool_definitions(enabled_toolsets=[ts])}
    out[ts] = bool(want & got)
print("AGOS-TOOLS " + json.dumps(out))
"""
# Run in Hermes's runtime by tools_catalog: every toolset Hermes offers, and the
# services each can use (Hermes's own `hermes tools` list).
_TOOLS_CATALOG = r"""
import json, logging
logging.disable(logging.CRITICAL)
from hermes_cli import tools_config as tc
from hermes_cli.config import load_config
from toolsets import TOOLSETS
try:
    from hermes_cli.tools_config_post_setup import _POST_SETUP_AUTH_READY as _AUTH
except ImportError:
    _AUTH = {}
config = load_config()
out = []
for entry in tc.CONFIGURABLE_TOOLSETS:
    key, label, hint = (list(entry) + ["", ""])[:3]
    label = " ".join(w for w in str(label).split() if w.isascii())
    provs = []
    cat = tc.TOOL_CATEGORIES.get(key)
    if cat:
        try:
            visible = tc._visible_providers(cat, config)
        except Exception:
            visible = cat.get("providers") or []
        for p in visible:
            provs.append({
                "name": str(p.get("name") or ""),
                "badge": str(p.get("badge") or ""),
                "about": str(p.get("tag") or ""),
                "env": [
                    {"key": str(e.get("key") or ""), "prompt": str(e.get("prompt") or ""),
                     "url": str(e.get("url") or "")}
                    for e in (p.get("env_vars") or []) if isinstance(e, dict)
                ],
                "nous": bool(p.get("requires_nous_auth")),
                "login": str(p.get("post_setup") or ""),
                # the engine's own list of post_setup steps that are sign-ins, not installs.
                "login_is_auth": str(p.get("post_setup") or "") in _AUTH,
            })
    about = str((TOOLSETS.get(key) or {}).get("description") or hint or "")
    out.append({"key": str(key), "label": label or str(key), "about": about, "providers": provs})
print("AGOS-CATALOG " + json.dumps(out))
"""

# Run in Hermes's runtime by save_credentials: provider keys into one home the way
# Hermes saves them itself (`hermes config set`, the dashboard): .env, config.yaml
# copies of the old value and the credential pool in auth.json
# (hermes_cli/credential_lifecycle.py).
_CREDENTIALS = r"""
import json
from hermes_cli.credential_lifecycle import (
    remove_provider_env_credential, save_provider_env_credential)
job = json.loads(@JOB@)
for key in job.get("drop", []):
    remove_provider_env_credential(key)
for key, value in job.get("set", {}).items():
    save_provider_env_credential(key, value)
print("AGOS-CREDENTIALS ok")
"""

# Run in Hermes's runtime by set_tool_service: the service a toolset uses, chosen
# the way Hermes's own dashboard does it (its keys into the profile's .env).
_TOOL_SERVICE = r"""
import json
from hermes_cli.config import load_config, save_config, save_env_value, remove_env_value
from hermes_cli.tools_config import apply_provider_selection
job = json.loads(@JOB@)
for key, value in job.get("env", {}).items():
    save_env_value(key, value)
for key in job.get("drop", []):
    remove_env_value(key)
if job.get("provider"):
    config = load_config()
    apply_provider_selection(job["toolset"], job["provider"], config)
    save_config(config)
    if job.get("install"):
        from hermes_cli.tools_config import TOOL_CATEGORIES, _post_setup_already_installed
        chosen = [p for p in TOOL_CATEGORIES.get(job["toolset"], {}).get("providers", [])
                  if p.get("name") == job["provider"]]
        step = chosen[0].get("post_setup") if chosen else None
        if step and step not in job.get("not_installs", []) and not _post_setup_already_installed(step):
            print("AGOS-INSTALL " + step)
print("AGOS-SERVICE ok")
"""

# Run in Hermes's runtime by tool_services_in: the service each toolset of this
# home uses now, as Hermes's own picker finds it (hermes_cli/tools_config_providers.py
# _detect_active_provider_index :542 over _visible_providers :142; its 0 is only
# kept when that row really is active or has its keys, like the dashboard's
# web_routers/tools.py get_toolset_config).
_TOOL_ACTIVE = r"""
import json, logging
logging.disable(logging.CRITICAL)
from hermes_cli import tools_config as tc
from hermes_cli.config import load_config
config = load_config()
out = {}
for key, cat in tc.TOOL_CATEGORIES.items():
    try:
        rows = tc._visible_providers(cat, config)
        if not rows:
            continue
        row = rows[tc._detect_active_provider_index(rows, config)]
        real = tc._is_provider_active(row, config) or (
            bool(row.get("env_vars")) and tc._provider_env_ready(row))
        out[str(key)] = str(row.get("name") or "") if real else None
    except Exception:
        continue
print("AGOS-ACTIVE " + json.dumps(out))
"""

# Run in Hermes's runtime by command_menu: the "/" menu Hermes's Telegram pushes
# (plugins/platforms/telegram/adapter.py _register_command_menu builds it with
# hermes_cli/commands_platforms.py telegram_menu_commands :282, capped by
# telegram_menu_max_commands :146): built-ins, plugin commands, skill commands.
_COMMAND_MENU = r"""
import json, logging
logging.disable(logging.CRITICAL)
from hermes_cli.commands_platforms import telegram_menu_commands, telegram_menu_max_commands
menu, _hidden = telegram_menu_commands(max_commands=telegram_menu_max_commands())
print("AGOS-MENU " + json.dumps([{"command": n, "description": d} for n, d in menu]))
"""


# The tools that work only with a service set up in Hermes (the others always do).
SERVICE_TOOLSETS = ("web", "image_gen", "video_gen", "x_search", "tts")
TOOLS_CHECK_TTL = 300.0


def tool_readiness(self: "HermesEngine", workspace_id: str) -> dict[str, bool]:
    """Which of the tools that need a service really work in this workspace, as
    its Hermes decides (checked in Hermes's runtime, ~1 s). Kept: once it is
    TOOLS_CHECK_TTL old, or a file Hermes reads for it changed (the profile's
    config, keys and logins), the last answer comes at once and Hermes is asked
    again behind the page; after AGOS changed the workspace's tools
    (forget_tools) it is asked before the page shows. {} when Hermes can't say."""
    home = self.profile_home(workspace_id)
    files_stamp = (
        read_cache.file_stamp(home / "config.yaml", home / ".env", home / "auth.json"),
        int(time.monotonic() // TOOLS_CHECK_TTL),
    )
    try:
        found = self._tools_seen.get(
            workspace_id, files_stamp, lambda: self._check_tools(home), stale_ok=True
        )
    except (EngineError, OSError, subprocess.TimeoutExpired, ValueError):
        return {}
    return dict(found)


def _check_tools(self: "HermesEngine", home: Path) -> dict[str, bool]:
    argv = list(self._runtime_argv())
    argv[-1] = argv[-1].replace(JUDGE_RUN, "exec(sys.stdin.read())")
    script = _TOOL_CHECK.replace("@SETS@", repr(json.dumps(list(SERVICE_TOOLSETS))))
    env = child_env({**self._env(), "HERMES_HOME": str(home)})
    off_loop("hermes tool check")
    done = subprocess.run(  # noqa: S603 - Hermes's own launcher, fixed argv
        argv,
        input=script,
        capture_output=True,
        text=True,
        timeout=hermes_wait(90),
        env=env,
        check=False,
        start_new_session=True,
    )
    hermes_contract.ran(done)
    lines = [ln for ln in done.stdout.splitlines() if ln.startswith("AGOS-TOOLS ")]
    if done.returncode != 0 or not lines:
        log.info("tool check failed (%s): %s", done.returncode, done.stderr[-300:])
        raise EngineError(f"The engine's tool check failed ({done.returncode})")
    return {str(k): bool(v) for k, v in json.loads(lines[-1][len("AGOS-TOOLS ") :]).items()}


def tools_catalog(self: "HermesEngine") -> list[dict[str, Any]]:
    """Every toolset Hermes offers and its services (read in Hermes's runtime)."""
    argv = list(self._runtime_argv())
    argv[-1] = argv[-1].replace(JUDGE_RUN, "exec(sys.stdin.read())")
    env = child_env({**self._env(), "HERMES_HOME": str(self.settings.hermes_home)})
    off_loop("hermes tools catalog")
    done = subprocess.run(  # noqa: S603 - Hermes's own launcher, fixed argv
        argv,
        input=_TOOLS_CATALOG,
        capture_output=True,
        text=True,
        timeout=hermes_wait(120),
        env=env,
        check=False,
        start_new_session=True,
    )
    hermes_contract.ran(done)
    lines = [ln for ln in done.stdout.splitlines() if ln.startswith("AGOS-CATALOG ")]
    if done.returncode != 0 or not lines:
        raise EngineError(f"The engine's tools list not read: {done.stderr[-300:]}")
    found: list[dict[str, Any]] = json.loads(lines[-1][len("AGOS-CATALOG ") :])
    return found


def save_credentials(
    self: "HermesEngine", home: Path, values: dict[str, str], drop: list[str]
) -> None:
    """Provider keys into one Hermes home, saved (or removed) by Hermes's own
    credential lifecycle. The values go on stdin, never argv."""
    argv = list(self._runtime_argv())
    argv[-1] = argv[-1].replace(JUDGE_RUN, "exec(sys.stdin.read())")
    script = _CREDENTIALS.replace("@JOB@", repr(json.dumps({"set": values, "drop": list(drop)})))
    env = child_env({**self._env(), "HERMES_HOME": str(home)})
    off_loop("hermes credentials")
    with home_write_lock(home):
        done = subprocess.run(  # noqa: S603 - Hermes's own launcher, fixed argv
            argv,
            input=script,
            capture_output=True,
            text=True,
            timeout=hermes_wait(120),
            env=env,
            check=False,
            start_new_session=True,
        )
    hermes_contract.ran(done)
    if done.returncode != 0 or "AGOS-CREDENTIALS ok" not in done.stdout:
        tail = done.stderr.strip().splitlines()[-1:] or ["no answer"]
        raise EngineError(f"The engine didn't save the keys: {tail[0][:200]}")


def set_tool_service(self: "HermesEngine", home: Path, job: dict[str, Any]) -> str | None:
    """A toolset's service in one Hermes home (Hermes writes it: config + .env).
    Returns Hermes's install step the service still needs (asked with "install")."""
    argv = list(self._runtime_argv())
    argv[-1] = argv[-1].replace(JUDGE_RUN, "exec(sys.stdin.read())")
    script = _TOOL_SERVICE.replace("@JOB@", repr(json.dumps(job)))
    env = child_env({**self._env(), "HERMES_HOME": str(home)})
    off_loop("hermes tool service")
    with home_write_lock(home):
        done = subprocess.run(  # noqa: S603 - Hermes's own launcher, fixed argv
            argv,
            input=script,
            capture_output=True,
            text=True,
            timeout=hermes_wait(120),
            env=env,
            check=False,
            start_new_session=True,
        )
    hermes_contract.ran(done)
    if done.returncode != 0 or "AGOS-SERVICE ok" not in done.stdout:
        tail = done.stderr.strip().splitlines()[-1:] or ["no answer"]
        raise EngineError(f"The engine didn't take it: {tail[0][:200]}")
    self._tools_seen.drop()
    steps = [ln[13:].strip() for ln in done.stdout.splitlines() if ln.startswith("AGOS-INSTALL ")]
    return steps[-1] if steps else None


def tool_services_in(self: "HermesEngine", home: Path) -> dict[str, str | None]:
    """The service each toolset of one Hermes home uses now (toolset → its
    name in Hermes's list, None when none is set up), read in Hermes's runtime
    from the home's own config.yaml/.env/auth (and, through Hermes's .env load,
    the managed scope). Kept while what those files hold is the same (a change
    made in Hermes shows at once); one run at a time per home."""
    return dict(
        self._services.get(
            str(home),
            read_cache.content_stamp(
                home / "config.yaml",
                home / ".env",
                home / "auth.json",
                *managed_files(self.settings.managed_home),
            ),
            lambda: self._tool_services_now(home),
        )
    )


def _tool_services_now(self: "HermesEngine", home: Path) -> dict[str, str | None]:
    argv = list(self._runtime_argv())
    argv[-1] = argv[-1].replace(JUDGE_RUN, "exec(sys.stdin.read())")
    env = child_env({**self._env(), "HERMES_HOME": str(home)})
    off_loop("hermes tool services")
    done = subprocess.run(  # noqa: S603 - Hermes's own launcher, fixed argv
        argv,
        input=_TOOL_ACTIVE,
        capture_output=True,
        text=True,
        timeout=hermes_wait(120),
        env=env,
        check=False,
        start_new_session=True,
    )
    hermes_contract.ran(done)
    lines = [ln for ln in done.stdout.splitlines() if ln.startswith("AGOS-ACTIVE ")]
    if done.returncode != 0 or not lines:
        raise EngineError(f"The engine's tool services not read: {done.stderr[-300:]}")
    found = {
        str(k): (str(v) if v else None)
        for k, v in json.loads(lines[-1][len("AGOS-ACTIVE ") :]).items()
    }
    return found


def command_menu(self: "HermesEngine", workspace_id: str) -> list[dict[str, str]]:
    """Hermes's own "/" menu for this workspace's root (what its Telegram shows),
    built by Hermes's registry in its runtime. Kept while the root's config and
    AGOS's policy file (its member commands) hold: a change there is asked for
    before the menu shows. What only Hermes's code adds (its skills' and
    plugins' commands) is read again behind the composer each minute, so the
    "/" list never waits on Hermes's start but after a change of those files."""
    home = self.profile_home(workspace_id)
    mark = read_cache.file_stamp(home / "config.yaml", home / "agos-guard.json")
    found = self._menus.get(
        (workspace_id, mark),
        int(time.monotonic() // 60),
        lambda: self._read_menu(home),
        stale_ok=True,
    )
    return list(found)


def _read_menu(self: "HermesEngine", home: Path) -> list[dict[str, str]]:
    argv = list(self._runtime_argv())
    argv[-1] = argv[-1].replace(JUDGE_RUN, "exec(sys.stdin.read())")
    env = child_env({**self._env(), "HERMES_HOME": str(home)})
    off_loop("hermes command menu")
    done = subprocess.run(  # noqa: S603 - Hermes's own launcher, fixed argv
        argv,
        input=_COMMAND_MENU,
        capture_output=True,
        text=True,
        timeout=hermes_wait(60),
        env=env,
        check=False,
        start_new_session=True,
    )
    hermes_contract.ran(done)
    lines = [ln for ln in done.stdout.splitlines() if ln.startswith("AGOS-MENU ")]
    if done.returncode != 0 or not lines:
        raise EngineError(f"The engine's command menu not read: {done.stderr[-300:]}")
    return [
        {"command": str(c.get("command") or ""), "description": str(c.get("description") or "")}
        for c in json.loads(lines[-1][len("AGOS-MENU ") :])
        if isinstance(c, dict)
    ]


def tools_install(self: "HermesEngine", home: Path, step: str, log: Path) -> None:
    """Hermes's own install for a service (`hermes tools post-setup`), in the
    background, like Hermes's dashboard does when a tool is turned on."""
    log.parent.mkdir(parents=True, exist_ok=True)
    env = child_env({**self._env(), "HERMES_HOME": str(home)})
    off_loop("hermes tools post-setup")
    with log.open("ab") as out:
        subprocess.Popen(  # noqa: S603 - Hermes's own CLI, fixed argv
            [self.settings.hermes_bin, "tools", "post-setup", step],
            stdout=out,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )


def forget_tools(self: "HermesEngine", workspace_id: str) -> None:
    self._tools_seen.drop(workspace_id)


def tool_keys(
    self: "HermesEngine", home: Path, job: dict[str, Any], secret: str = ""
) -> dict[str, Any]:
    """A workspace tool key in this Hermes home (engine/tool_keys.py SCRIPT, in
    Hermes's runtime): {"do": "facts", "slug", "names"} | {"do": "save" |
    "remove" | "test", "name", "probe"?} | {"do": "share", "drop"} (a member gets its
    root's keys). The key(s) go on stdin only; the answer
    holds names and yes/no, never a value."""
    from agos_core.engine.models import hermes_python
    from agos_core.engine.tool_keys import SCRIPT

    try:
        python = hermes_python(self.settings)
    except (OSError, RuntimeError) as error:
        raise EngineError("The engine isn't installed where the settings say") from error
    lock = (
        home_write_lock(home)
        if job.get("do") in ("save", "remove", "share")
        else contextlib.nullcontext()
    )
    try:
        with lock:
            done = subprocess.run(  # noqa: S603 - Hermes's own runtime, fixed argv; key on stdin
                [python, "-c", SCRIPT, json.dumps(job)],
                input=secret,
                capture_output=True,
                text=True,
                timeout=hermes_wait(90),
                env=child_env({**self._env(), "HERMES_HOME": str(home)}),
                check=False,
                start_new_session=True,
            )
        hermes_contract.ran(done)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise EngineError("The engine didn't answer about the key") from error
    lines = [ln for ln in done.stdout.splitlines() if ln.startswith("AGOS-TOOLKEYS ")]
    if done.returncode != 0 or not lines:
        # Never Hermes's stderr: a traceback could quote a value.
        log.info("tool key job %s failed (exit %s)", job.get("do"), done.returncode)
        raise EngineError("The engine didn't answer about the key")
    found: dict[str, Any] = json.loads(lines[-1][len("AGOS-TOOLKEYS ") :])
    if found.get("error"):
        log.info("tool key job %s: Hermes said %s", job.get("do"), found["error"])
        raise EngineError("The engine didn't take the key")
    return found
