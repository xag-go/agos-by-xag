"""Settings → General → Update AGOS: the same update as `agos update` on the machine.

AGOS's own release (git: the newest release tag of the install's channel, or the
branch the installer cloned on the main channel, ADR 0028) and the Hermes commit
that release pins (deploy/hermes.pin). The check is read-only (`git fetch` and the
new commits' titles). "Update now" starts `agos update --yes` (deploy/agos) as
its own systemd user service of the AGOS user, outside the core: the update
stops the core and the web, backs up first, builds the new release, starts it
again, and rolls back by itself on a failure. Its progress is a small JSON file
in the data folder (`system/agos-update.json`) that `agos update` writes and
`status` reads, so the card can follow it across the restart.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agos_core.actions import release_channel
from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.db.app_settings import get_setting, set_setting
from agos_core.engine.loop_guard import off_loop

KEY_CHECK = "agos_update.check"
RUNNING = ("queued", "starting", "backup", "stopping", "code", "hermes", "build", "sandbox",
           "starting-up", "rollback")  # fmt: skip
STALE_S = 3 * 3600  # a "running" update older than this is not running any more
CONF = Path(os.environ.get("AGOS_CONF", "/etc/agos/agos.conf"))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _conf() -> dict[str, str]:
    """The installer's settings (/etc/agos/agos.conf: KEY=value lines)."""
    out: dict[str, str] = {}
    try:
        text = CONF.read_text()
    except OSError:
        return out
    for line in text.splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() and not name.lstrip().startswith("#"):
            out[name.strip()] = value.strip()
    return out


def app_dir() -> Path:
    configured = os.environ.get("AGOS_APP_DIR") or _conf().get("AGOS_APP")
    return Path(configured) if configured else Path(__file__).resolve().parents[5]


def _ref() -> str:
    return _conf().get("AGOS_REF") or "main"


def _agos_bin() -> str:
    return os.environ.get("AGOS_BIN") or shutil.which("agos") or "/usr/local/bin/agos"


def state_file(core: Core) -> Path:
    return core.layout.root / "system" / "agos-update.json"


def _git(*args: str, timeout: float = 120) -> str:
    off_loop("git " + args[0])
    done = subprocess.run(  # noqa: S603 - fixed git arguments
        ["git", "-C", str(app_dir()), *args],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if done.returncode != 0:
        raise ActionError(
            f"git {args[0]} failed: {(done.stderr or done.stdout).strip()[:300]}", 502
        )
    return done.stdout.strip()


def _state(core: Core) -> dict[str, Any] | None:
    try:
        found = json.loads(state_file(core).read_text())
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def running(state: dict[str, Any] | None) -> bool:
    if not state or state.get("phase") not in RUNNING:
        return False
    try:
        started = datetime.fromisoformat(str(state.get("started_at", "")).replace("Z", "+00:00"))
    except ValueError:
        return True
    return time.time() - started.timestamp() < STALE_S


def version(folder: Path | None = None) -> str:
    """The release version (the repository's VERSION file, e.g. "0.1.0"); "" if missing."""
    try:
        return ((folder or app_dir()) / "VERSION").read_text().strip()
    except OSError:
        return ""


def current() -> dict[str, str]:
    found = version()
    try:
        sha = _git("rev-parse", "HEAD", timeout=20)
        date = _git("log", "-1", "--format=%cs", timeout=20)
    except (ActionError, OSError, subprocess.SubprocessError):
        return {"version": found, "sha": "", "date": ""}
    return {"version": found, "sha": sha, "date": date}


def installed() -> bool:
    """Installed by the AGOS installer from git (the update needs both)."""
    conf = _conf()
    return bool(conf) and not conf.get("AGOS_LOCAL_REPO") and (app_dir() / ".git").exists()


def status(core: Core) -> dict[str, Any]:
    return {
        "installed": installed(),
        "current": current(),
        "check": get_setting(core.db, KEY_CHECK, None),
        "state": _state(core),
    }


def _target(channel: str, now: str) -> tuple[str, str]:
    """The commit the channel's update goes to, and its name (the tag, or the branch).
    Only forward: a release this code already holds (an install on main past the
    newest release) is no update: the target is then `now`."""
    if channel == "main":
        ref = _ref()
        _git("fetch", "-q", "origin", ref, timeout=180)
        return _git("rev-parse", "FETCH_HEAD"), ref
    # Never --force: a release tag that changed on the server is refused, not taken.
    _git("fetch", "-q", "--tags", "origin", timeout=180)
    tag = release_channel.newest(_git("tag", "-l", "v*").splitlines(), channel)
    if not tag:
        return now, ""
    found = _git("rev-parse", f"{tag}^{{commit}}")
    if found != now and _git("merge-base", now, found) == now:
        return found, tag
    return now, tag


def run_check(core: Core) -> dict[str, Any]:
    """Check Update: is there a newer AGOS on the release branch? (read-only)"""
    if not installed():
        raise ActionError(
            "This AGOS wasn't installed with the installer: update it the way you installed it."
        )
    if running(_state(core)):
        raise ActionError("An update is running.")
    channel = release_channel.channel_of(_conf())
    now = _git("rev-parse", "HEAD")
    target, release = _target(channel, now)
    news: list[str] = []
    if now != target:
        log = _git("log", "--format=%s", f"{now}..{target}")
        news = [line for line in log.splitlines() if line.strip()][:30]
    pin_now = (app_dir() / "deploy" / "hermes.pin").read_text().strip()
    pin_new = _git("show", f"{target}:deploy/hermes.pin") if now != target else pin_now
    target_version = version()
    if now != target:
        try:
            target_version = _git("show", f"{target}:VERSION").strip()
        except ActionError:  # a release from before the VERSION file
            target_version = ""
    record = {
        "at": _now(),
        "ref": _ref(),
        "channel": channel,
        "release": release if now != target else None,
        "current": now,
        "target": target if now != target else None,
        "target_version": target_version,
        "news": news,
        "hermes_changes": pin_new != pin_now,
    }
    set_setting(core.db, KEY_CHECK, record)
    return record


def _launch(args: list[str]) -> None:
    """Starts the update as its own systemd user service: it outlives the core."""
    env = {**os.environ, "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}"}
    done = subprocess.run(  # noqa: S603 - fixed arguments
        args, env=env, capture_output=True, text=True, timeout=60, check=False
    )
    if done.returncode != 0:
        raise ActionError(
            f"The update didn't start: {(done.stderr or done.stdout).strip()[:300]}", 502
        )


def start_update(core: Core) -> dict[str, Any]:
    """Update now (the popup's yes): `agos update --yes`, backups first."""
    if not installed():
        raise ActionError(
            "This AGOS wasn't installed with the installer: update it the way you installed it."
        )
    if running(_state(core)):
        raise ActionError("An update is already running.")
    check = get_setting(core.db, KEY_CHECK, None)
    if not isinstance(check, dict) or not check.get("target"):
        raise ActionError("Check for an update first.")
    state = {"phase": "queued", "started_at": _now(), "from": check["current"],
             "to": check["target"], "steps": [], "error": None}  # fmt: skip
    path = state_file(core)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state))
    unit = f"agos-update-{time.strftime('%Y%m%d%H%M%S', time.gmtime())}"
    try:
        _launch(["systemd-run", "--user", "--quiet", "--collect", f"--unit={unit}",
                 _agos_bin(), "update", "--yes"])  # fmt: skip
    except (ActionError, OSError, subprocess.SubprocessError) as error:
        state.update(phase="failed", error=str(error))
        path.write_text(json.dumps(state))
        raise ActionError(str(error), 502) from error
    set_setting(core.db, KEY_CHECK, None)
    return state
