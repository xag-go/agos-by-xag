"""The owner's timezone (Settings → General): Hermes's own `timezone` setting.

Hermes reads `timezone` through its effective config (hermes_time.py
`_resolve_timezone_name` → hermes_cli/config_effective.py, managed overlay
included: the agent's clock and every cron schedule; empty = the server's local
time). AGOS keeps no copy: General Settings writes it with `hermes config set
timezone <zone>` (`config unset` to clear it) into Hermes's managed scope, the one
config.yaml every Hermes process AGOS runs reads (actions/hermes_managed.py), and
reads it back from there. Only each workspace profile's sandbox `TZ`
(`terminal.docker_env`, a per-profile list AGOS's sandbox rules write) is set per
home.
"""

from __future__ import annotations

import logging
from pathlib import Path

from agos_core.context import Core
from agos_core.domain.time_zone import zone_of as zone_of
from agos_core.engine.loop_guard import off_loop

log = logging.getLogger("agos.owner_time")

CONFIG_KEY = "timezone"  # Hermes's own key (config.yaml)


def homes(core: Core) -> list[Path]:
    """Every Hermes home of this AGOS: the shared home, then each workspace's
    profiles (its root and members, or its profiles in the shared home)."""
    engine = core.engine
    if engine is None:
        return []
    out = [engine.settings.hermes_home]
    for row in core.db.execute("SELECT id FROM workspaces"):
        for name in engine.own_profiles(str(row["id"])):
            home = engine.home_of(name)
            if home is not None and (home / "config.yaml").is_file() and home not in out:
                out.append(home)
    return out


def write_home(core: Core, home: Path, name: str) -> bool:
    """A workspace profile's sandbox `TZ` (`terminal.docker_env`, engine/rules.py
    sandbox_env). True when it changed. (Hermes's own `timezone` is the managed
    scope's: set_zone.)"""
    engine = core.engine
    if engine is None:
        return False
    if home == engine.settings.hermes_home or not (home / "config.yaml").is_file():
        return False  # not a workspace profile (yet): it gets it when it's made
    return _write_sandbox_zone(core, home, name)


def _hermes(core: Core, home: Path, args: list[str]) -> None:
    from agos_core.engine.hermes import home_write_lock

    engine = core.engine
    assert engine is not None
    off_loop("hermes owner time")
    # Hermes's config set rewrites the whole config.yaml: one writer per home at a
    # time, or a concurrent write to this home (a library switch, a settings row)
    # could be lost.
    with home_write_lock(home):
        engine.runner.run(
            [engine.settings.hermes_bin, *args],
            timeout=60,
            env={**engine._env(), "HERMES_HOME": str(home)},
        )


def _write_sandbox_zone(core: Core, home: Path, name: str) -> bool:
    """The sandbox's `TZ` (Hermes passes only `terminal.docker_env` into it, so
    `date` there would say UTC). Hermes reads it for each new terminal session."""
    import json

    from agos_core.engine import config_file
    from agos_core.engine.rules import sandbox_env

    current = config_file.get(config_file.read(home), "terminal.docker_env")
    have = json.dumps(current) if isinstance(current, dict) else "{}"
    wanted = sandbox_env(have, name)
    if json.loads(wanted) == (current if isinstance(current, dict) else {}):
        return False
    _hermes(core, home, ["config", "set", "terminal.docker_env", wanted])
    return True


def set_zone(core: Core, name: str) -> list[Path]:
    """Into Hermes's managed scope (each Hermes picks it up on its next prompt or
    cron tick) and every workspace profile's sandbox. Returns the homes not written
    (logged; general_sync retries the sandboxes later)."""
    from agos_core.actions import hermes_managed
    from agos_core.engine.hermes import EngineError

    failed: list[Path] = []
    if core.engine is None:
        return failed
    try:
        if name:
            hermes_managed.write(core, {CONFIG_KEY: name})
        else:
            hermes_managed.write(core, {}, (CONFIG_KEY,))
    except (EngineError, OSError) as error:
        log.warning("timezone not written into Hermes's managed scope: %s", error)
        failed.append(core.engine.settings.managed_home)

    def one(home: Path) -> None:
        try:
            write_home(core, home, name)
        except (EngineError, OSError) as error:
            log.warning("sandbox timezone not written into %s: %s", home, error)
            failed.append(home)

    # Every profile's sandbox TZ, up to 4 homes at once (each its own write lock;
    # one after another was ~0.65 s per profile, 16 live).
    targets = homes(core)[1:]
    if targets:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=min(4, len(targets))) as pool:
            list(pool.map(one, targets))
    failed.sort(key=lambda home: -1 if home not in targets else targets.index(home))
    return failed


def owner_zone(core: Core) -> str:
    """As Hermes has it (its managed scope)."""
    if core.engine is None:
        return ""
    return core.engine.owner_zone()


def save_timezone(core: Core, timezone: str) -> str:
    """Hermes's own `timezone` into every workspace (the page and the Co-Founder)."""
    from agos_core.actions.errors import ActionError

    name = timezone.strip()
    if name and zone_of(name) is None:
        raise ActionError(f"“{name}” isn't a timezone (e.g. Europe/London).")
    if core.engine is None:
        raise ActionError("Hermes isn't available.", status=503)
    failed = set_zone(core, name)
    if core.engine.settings.hermes_home in failed:
        raise ActionError("Hermes didn't save the timezone. Try again in a moment.", status=502)
    return name
