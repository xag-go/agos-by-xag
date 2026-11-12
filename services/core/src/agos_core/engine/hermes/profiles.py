"""A profile's life in its workspace root: create (the root itself or a member under
it), its display name and description, its API address and key, and delete.

Owns: Hermes's profile CLI and profile.yaml writer for these, the root marker, and the
profile's API_SERVER_* lines in its .env.

Must not: Configure the sandbox (apply in the facade) or stop a running gateway
(gateway_run.py park, which delete_profile calls).

Part of engine/hermes (HermesEngine binds these functions as its methods).
"""

import contextlib
import json
import logging
import secrets
import socket
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from agos_core.engine import hermes_contract
from agos_core.engine.hermes.gateway_limits import API_HOST
from agos_core.engine.hermes.runtime_env import child_env
from agos_core.engine.loop_guard import off_loop
from agos_core.engine.root_unit import MARKER as ROOT_MARKER
from agos_core.engine.waits import hermes_wait
from agos_core.hermes_gateway.errors import EngineError

log = logging.getLogger("agos.engine")

if TYPE_CHECKING:
    from agos_core.engine.hermes import HermesEngine

__all__ = [
    "_DESCRIPTION",
    "_DISPLAY_NAME",
    "_cli_finds",
    "_delete_in_root",
    "_free_port",
    "_make_in_root",
    "_profile_cli",
    "_profile_meta",
    "_profile_of",
    "_write_api_env",
    "api",
    "delete_profile",
    "ensure_profile",
    "set_description",
    "set_display_name",
]


# Run in Hermes's runtime by set_display_name for a MEMBER (a named profile) or to
# clear a name: Hermes's own profile.yaml writer (hermes_cli/profiles.py
# write_profile_meta). Hermes's CLI sets a display name only for `default` (a root:
# `hermes profile rename default <name>`, profiles.py rename_profile:2420); for a
# named profile `rename` changes its id, and it refuses an empty name (:2421).
_DISPLAY_NAME = r"""
import sys
from pathlib import Path
from hermes_cli.profiles import write_profile_meta
write_profile_meta(Path(sys.argv[1]), display_name=sys.argv[2])
print("AGOS-META ok")
"""
# The profile's description when it is EMPTY (what `hermes profile describe --text`
# writes: the text and description_auto False; the CLI can't write an empty one:
# hermes_cli/profile_cmd.py _profile_describe, an empty --text only shows it).
_DESCRIPTION = r"""
import sys
from pathlib import Path
from hermes_cli.profiles import write_profile_meta
write_profile_meta(Path(sys.argv[1]), description=sys.argv[2], description_auto=False)
print("AGOS-META ok")
"""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((API_HOST, 0))
        return int(probe.getsockname()[1])


def _profile_of(home: Path) -> tuple[Path, str]:
    """(the Hermes root, the profile's name there) of a profile home: a member is
    `<root>/profiles/<name>`, a root is its own `default`."""
    if home.parent.name == "profiles":
        return home.parent.parent, home.name
    return home, "default"


def _cli_finds(self: "HermesEngine", home: Path) -> bool:
    """Hermes's profile CLI resolves `default` and a member's name from its
    default root (hermes_constants.py get_default_hermes_root): a root inside
    ~/.hermes (a throwaway one under its cache) would be read as ~/.hermes
    itself, so there the profile's own path is written instead."""
    root, _name = self._profile_of(home)
    native = (self.settings.host_home / ".hermes").resolve()
    here = root.resolve()
    return here == native or not here.is_relative_to(native)


def _profile_cli(self: "HermesEngine", home: Path, *args: str) -> None:
    # The callers hold the profile's own lock (engine/profile_meta.py locked).
    root, _name = self._profile_of(home)
    off_loop("hermes profile")
    self.runner.run(
        [self.settings.hermes_bin, "profile", *args],
        timeout=60,
        env={**self._env(), "HERMES_HOME": str(root)},
    )


def set_display_name(self: "HermesEngine", home: Path, title: str) -> None:
    """The profile's presentation name in its profile.yaml (only that key
    changes): a root's with Hermes's CLI (`hermes profile rename default
    <name>`), a member's or an empty one with Hermes's write_profile_meta in its
    runtime (no CLI for those)."""
    _root, name = self._profile_of(home)
    if name == "default" and title.strip() and self._cli_finds(home):
        self._profile_cli(home, "rename", "default", title.strip())
        return
    self._profile_meta(home, _DISPLAY_NAME, title, "name")


def set_description(self: "HermesEngine", home: Path, text: str) -> None:
    """The profile's description in its profile.yaml: Hermes's CLI (`hermes
    profile describe <name> --text`, in its root); an empty one with Hermes's
    write_profile_meta in its runtime (the CLI can't clear it)."""
    _root, name = self._profile_of(home)
    if text.strip() and self._cli_finds(home):
        self._profile_cli(home, "describe", name, "--text", text.strip())
        return
    self._profile_meta(home, _DESCRIPTION, text, "description")


def _profile_meta(self: "HermesEngine", home: Path, script: str, value: str, what: str) -> None:
    from agos_core.engine.models import hermes_python

    try:
        python = hermes_python(self.settings)
    except (OSError, RuntimeError) as error:
        raise EngineError("The engine isn't installed where the settings say") from error
    off_loop("hermes profile meta")
    try:
        done = subprocess.run(  # noqa: S603 - Hermes's own runtime, fixed argv
            [python, "-c", script, str(home), value],
            capture_output=True,
            text=True,
            timeout=hermes_wait(60),
            env=child_env({**self._env(), "HERMES_HOME": str(home)}),
            check=False,
            start_new_session=True,
        )
        hermes_contract.ran(done)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise EngineError(f"The engine did not write the profile's {what}") from error
    if done.returncode != 0 or "AGOS-META ok" not in done.stdout:
        log.info("profile %s not written (%s): %s", what, done.returncode, done.stderr[-300:])
        raise EngineError(f"The engine did not write the profile's {what}")


# ---- profile ---------------------------------------------------------


def ensure_profile(self: "HermesEngine", workspace_id: str) -> bool:
    """Creates the profile if missing. Returns True when it was created."""
    if self.not_migrated(workspace_id):
        # Still in the shared home (or being copied by migrate_root, before its
        # root is marked): AGOS neither makes nor writes a root over it.
        raise EngineError(
            "this workspace is still in the shared home: move it onto its own "
            "root first (python -m agos_core.migrate_root)"
        )
    home = self.profile_home(workspace_id)
    if (home / "config.yaml").is_file():
        try:
            self.api(workspace_id)
        except (EngineError, FileNotFoundError):
            self._write_api_env(workspace_id)
        self.bundled_skills(workspace_id)
        return False
    self._make_in_root(workspace_id)
    self._write_api_env(workspace_id)
    return True


def _make_in_root(self: "HermesEngine", key: str) -> None:
    """A new profile in the workspace's own root: the Co-Founder is the root itself
    (Hermes sets a home up on its first command, bundled skills included), a
    member is a named profile under it (`hermes profile create`, run IN that root,
    so it can never land in another workspace's root or the shared home)."""
    ws, sub = self.split(key)
    root = self.root(ws)
    if sub is None:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        marker = root / ROOT_MARKER
        if not marker.is_file():
            marker.write_text(
                json.dumps({"workspace": ws, "profile": self.profile(ws)}, sort_keys=True)
            )
        # Hermes's first command makes the home (config, skills, identity).
        off_loop("hermes config set")
        self.runner.run(
            [self.settings.hermes_bin, "config", "set", "terminal.backend", "docker"],
            timeout=600,
            env=self.hermes_env(ws),
        )
        return
    if not (root / "config.yaml").is_file():
        self._make_in_root(ws)
    if (self.profile_home(key) / ".env").is_file():
        return  # made in Hermes already (`hermes profile create` seeds its .env)
    # Its description, title and role are the team's to write (actions/team.py).
    off_loop("hermes profile create")
    self.runner.run(
        [self.settings.hermes_bin, "profile", "create", sub, "--no-alias"],
        timeout=120,
        env=self.hermes_env(ws),
    )


def _write_api_env(self: "HermesEngine", workspace_id: str) -> None:
    """The profile's API: loopback only, its own port and key."""
    from agos_core.engine import envfile

    envfile.rewrite(
        self.profile_home(workspace_id) / ".env",
        ("API_SERVER_", "GATEWAY_ALLOW_ALL_USERS"),
        [
            "API_SERVER_ENABLED=true",
            f"API_SERVER_HOST={API_HOST}",
            f"API_SERVER_PORT={_free_port()}",
            f"API_SERVER_KEY={secrets.token_urlsafe(32)}",
        ],
    )


def api(self: "HermesEngine", workspace_id: str) -> tuple[str, str]:
    """(base URL, key) of the workspace's Hermes API. Never shown to a model."""
    values: dict[str, str] = {}
    env_file = self.profile_home(workspace_id) / ".env"
    for line in env_file.read_text().splitlines():
        name, sep, value = line.partition("=")
        if sep:
            values[name.strip()] = value.strip()
    port, key = values.get("API_SERVER_PORT"), values.get("API_SERVER_KEY")
    if not port or not port.isdigit() or not key:
        raise EngineError("this workspace's engine is not set up yet")
    return f"http://{API_HOST}:{int(port)}", key


def delete_profile(self: "HermesEngine", workspace_id: str) -> None:
    """Workspace purged: its Hermes home (memory, sessions, keys) goes too."""
    if not self.profile_home(workspace_id).exists():
        return
    self.park(workspace_id)
    self.remove_network(workspace_id)
    self._clear_sandbox_dirs(workspace_id)
    import shutil

    shutil.rmtree(self.temp_dir(workspace_id), ignore_errors=True)
    self._delete_in_root(workspace_id)


def _delete_in_root(self: "HermesEngine", key: str) -> None:
    """A member: Hermes's own `profile delete` in its root. The Co-Founder: the
    whole root (Hermes has no command for a home itself), only when it is
    AGOS's (its marker) and sits under AGOS's roots folder."""
    import shutil

    ws, sub = self.split(key)
    with self._locks.hold(self.profile(key)):
        if sub is not None:
            with contextlib.suppress(EngineError):
                off_loop("hermes profile delete")
                self.runner.run(
                    [self.settings.hermes_bin, "profile", "delete", sub, "-y"],
                    timeout=120,
                    env=self.hermes_env(ws),
                )
            home = self.profile_home(key)
            if home.exists() and not any(home.iterdir()):
                with contextlib.suppress(OSError):
                    home.rmdir()
            return
        root = self.root(ws)
        roots = self.settings.roots_dir
        if not (root / ROOT_MARKER).is_file():
            raise EngineError("not a root AGOS made: left in place")
        if root.resolve().parent != roots.resolve():
            raise EngineError("the root is not in AGOS's roots folder: left in place")
        shutil.rmtree(root)
