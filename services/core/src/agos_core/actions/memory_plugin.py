"""Holographic memory in every profile, installed the Hermes way.

Every profile AGOS makes names `memory.provider: holographic` (engine/rules.py).
Since v0.22 Holographic is a plugin of Hermes's catalog, not part of its tree
(website/docs/user-guide/features/memory-providers.md, "Migrating from bundled
Holographic"): its code lives in `<home>/plugins/holographic`.

AGOS installs it right after a root or member profile is made, with Hermes's own
`hermes plugins install holographic --enable --yes-deps` in that profile's home
(the catalog's reviewed pin, its dependency check, the enable), in the background
so the profile is ready at once. That install is tried up to `TRIES` times (30 s,
then 60 s apart) when Hermes's installer fails, because AGOS starts a new
workspace's root and member installs at the same moment and they can collide.
The install writes the profile's config, so it holds that home's config lock for as
long as it downloads: a setup that makes a profile (a new workspace) wraps itself in
`after_setup`, and the installs it asks for start when it is done (its own config
writes never wait on GitHub).

Hermes has its own recovery (H: agent/agent_init.py `recover_at_startup`,
hermes_cli/memory_provider_migration.py: a provider that left core is installed at
the agent's start, with a backoff), but it runs inside the gateway, behind the
Landlock wall (engine/wall.py), where the catalog install can't finish. So AGOS,
unwalled, also tries again at its own start (`recover`) for every profile that
names Holographic and still lacks it (GitHub was down for all three tries).
"""

from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Iterator
from contextvars import ContextVar
from pathlib import Path

from agos_core.context import Core
from agos_core.engine import config_file
from agos_core.engine.hermes import EngineError
from agos_core.hermes_gateway import cli as hermes_cli

log = logging.getLogger("agos.memory_plugin")

PLUGIN = "holographic"
TRIES = 3  # the new profile's install, tried again only on a failure
PAUSE_S = 30.0

# The installs asked for inside an `after_setup` block (None: outside one).
_HELD: ContextVar[list[str] | None] = ContextVar("holographic_held", default=None)


def installed(home: Path) -> bool:
    """Hermes's catalog install of it is in the profile's own plugins folder."""
    return (home / "plugins" / PLUGIN / "plugin.yaml").is_file()


def wanted(home: Path) -> bool:
    """The profile names it as its memory provider."""
    try:
        cfg = config_file.read(home)
    except (OSError, ValueError):
        return False
    return bool(config_file.get(cfg, "memory.provider") == PLUGIN)


def ensure(core: Core, key: str) -> bool:
    """Installs it into this profile (engine key) when it names it and lacks it:
    one try. True when it is there now (a failure is tried again by `install_new`'s
    next try, or at AGOS's next start: `recover`)."""
    engine = core.engine
    if engine is None:
        return False
    home = engine.profile_home(key)
    if not (home / "config.yaml").is_file() or not wanted(home):
        return installed(home)
    if installed(home):
        return True
    try:
        hermes_cli.cli(
            engine, key, "plugins", "install", PLUGIN, "--enable", "--yes-deps", timeout=900
        )
    except EngineError as error:
        log.warning(
            "Holographic memory not installed in %s (AGOS tries again at its next start): %s",
            key,
            error,
        )
        return False
    if installed(home):
        log.info("Holographic memory installed in %s (Hermes's plugin catalog)", key)
    return installed(home)


@contextlib.contextmanager
def after_setup(core: Core) -> Iterator[None]:
    """The new profiles' installs asked for inside the block start when it ends
    (also when it fails: a profile it made still gets its install)."""
    held: list[str] = []
    token = _HELD.set(held)
    try:
        yield
    finally:
        _HELD.reset(token)
        for key in held:
            _start(core, key)


def install_new(core: Core, key: str) -> None:
    """A profile was just made: its one install, in the background (once the setup
    that made it is done, inside `after_setup`)."""
    if core.engine is None:
        return
    held = _HELD.get()
    if held is not None:
        if key not in held:
            held.append(key)
        return
    _start(core, key)


def _start(core: Core, key: str) -> None:
    def run() -> None:
        import time

        for attempt in range(TRIES):
            try:
                if ensure(core, key):
                    return
            except Exception:
                log.exception("Holographic memory install in %s failed", key)
            if attempt + 1 < TRIES:
                time.sleep(PAUSE_S * (attempt + 1))

    threading.Thread(target=run, name=f"holographic-{key}", daemon=True).start()


def recover(core: Core) -> list[str]:
    """AGOS's start: every profile that names Holographic and lacks it (its tries
    all failed) gets `install_new` again, in the background. Returns their keys."""
    engine = core.engine
    if engine is None:
        return []
    prefix = engine.settings.profile_prefix
    started: list[str] = []
    for row in core.db.execute("SELECT id FROM workspaces ORDER BY id"):
        workspace_id = str(row["id"])
        if not (engine.root(workspace_id) / "config.yaml").is_file():
            continue
        for name in engine.own_profiles(workspace_id):
            key = name[len(prefix) :] if name.startswith(prefix) else name
            home = engine.profile_home(key)
            if wanted(home) and not installed(home):
                install_new(core, key)
                started.append(key)
    if started:
        log.info("Holographic memory missing in %d profile(s): installing again", len(started))
    return started
