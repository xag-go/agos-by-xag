"""A workspace's Hermes names and folders: its root, profile homes, legacy homes, the
walled command lines that run in them, and the folders AGOS keeps beside them.

Owns: Pure naming and path rules (no Hermes run, no write besides making AGOS's own
folders).

Must not: Run Hermes or Docker, or create a profile (profiles.py).

Part of engine/hermes (HermesEngine binds these functions as its methods).
"""

from pathlib import Path
from typing import TYPE_CHECKING

from agos_core.engine import sandbox_broker as broker
from agos_core.engine.loop_guard import off_loop
from agos_core.engine.root_unit import MARKER as ROOT_MARKER
from agos_core.engine.rules import host_secret_dirs, profile_name

if TYPE_CHECKING:
    from agos_core.engine.hermes import HermesEngine

__all__ = [
    "ROOT_MARKER",
    "browser_dir",
    "forbidden",
    "hermes_env",
    "hermes_name",
    "home_in",
    "home_of",
    "is_member",
    "legacy_home",
    "lock_dir",
    "migrating",
    "not_migrated",
    "own_profiles",
    "profile",
    "profile_home",
    "root",
    "split",
    "temp_dir",
    "walled",
    "walled_cli",
    "walled_for_home",
]


# ---- names and paths -------------------------------------------------


def profile(self: "HermesEngine", workspace_id: str) -> str:
    return profile_name(self.settings.profile_prefix, workspace_id)


def own_profiles(self: "HermesEngine", workspace_id: str) -> list[str]:
    """The workspace's profile and its own (members, team agents: "<profile>--…")."""
    own = self.profile(workspace_id)
    names = [own]
    folder = self.root(workspace_id) / "profiles"
    if folder.is_dir():
        names += sorted(
            f"{own}--{p.name}"
            for p in folder.iterdir()
            if p.is_dir() and not p.name.startswith(".") and "--" not in p.name
        )
    return names


# ---- one Hermes root per workspace (ADR 0020) ---------------------------------
# AGOS keeps its own names ("agos-<ws>", "agos-<ws>--a-<agent>") everywhere (its
# database, docker labels, networks). In Hermes, the Co-Founder IS the workspace's
# root (Hermes's "default" profile) and a member is "<root>/profiles/<a-agent>".
# The shared home (~/.hermes) only keeps General Settings' login and keys.


def split(key: str) -> tuple[str, str | None]:
    """("<workspace>", "<member part>" | None) of an engine key."""
    workspace_id, sep, sub = key.partition("--")
    return workspace_id, (sub if sep else None)


def root(self: "HermesEngine", workspace_id: str) -> Path:
    """The workspace's own Hermes root."""
    return self.settings.roots_dir / self.profile(self.split(workspace_id)[0])


def legacy_home(self: "HermesEngine", key: str) -> Path:
    """Where the shared home kept this profile before ADR 0020. Only read: by
    agos_core.migrate_root, and so that AGOS never makes a fresh root over a
    workspace that still waits to be migrated."""
    return self.settings.hermes_home / "profiles" / self.profile(key)


def migrating(self: "HermesEngine", workspace_id: str) -> bool:
    """The workspace is being moved onto its own root (agos_core.migrate_root):
    AGOS starts none of its gateways until it is done."""
    ws = self.split(workspace_id)[0]
    return (self.settings.roots_dir / f"{self.profile(ws)}.agos-migrating").is_file()


def not_migrated(self: "HermesEngine", workspace_id: str) -> bool:
    """The workspace still lives in the shared home (no root of its own yet): it
    must be moved with agos_core.migrate_root before AGOS runs it."""
    ws = self.split(workspace_id)[0]
    return (self.legacy_home(ws) / "config.yaml").is_file() and not (
        self.root(ws) / ROOT_MARKER
    ).is_file()


def hermes_name(self: "HermesEngine", key: str) -> str:
    """The profile's name as Hermes knows it in its root ("default" for the
    Co-Founder, e.g. "a-writer" for a member)."""
    return self.split(key)[1] or "default"


def profile_home(self: "HermesEngine", workspace_id: str) -> Path:
    sub = self.split(workspace_id)[1]
    root = self.root(workspace_id)
    return root / "profiles" / sub if sub else root


def home_in(self: "HermesEngine", workspace_id: str, hermes_name: str) -> Path:
    """The home of a profile named as Hermes names it in this workspace's root
    (a Kanban assignee: "default", "a-writer")."""
    root = self.root(workspace_id)
    return root if hermes_name in ("", "default") else root / "profiles" / hermes_name


def home_of(self: "HermesEngine", profile: str) -> Path | None:
    """The home of one of AGOS's profile names ("agos-<ws>[--…]"), None for a
    name that is not AGOS's."""
    prefix = self.settings.profile_prefix
    if not profile.startswith(prefix) or len(profile) == len(prefix):
        return None
    return self.profile_home(profile[len(prefix) :])


def hermes_env(self: "HermesEngine", key: str) -> dict[str, str]:
    """The environment of a Hermes process for this profile (HOME, its home, the
    install's runtime, its root's own gateway lock folder and browser folder)."""
    return {
        **self._env(),
        "HERMES_HOME": str(self.profile_home(key)),
        "HERMES_GATEWAY_LOCK_DIR": str(self.lock_dir(key)),
        "BH_HOME": str(self.browser_dir(key)),
    }


def walled(self: "HermesEngine", key: str, command: list[str]) -> list[str]:
    """`command` behind the same cage and Landlock wall as this root's gateway. For
    every Hermes process AGOS starts that runs code the walled gateway can write
    (plugins, scripts): unwalled, a planted plugin would get AGOS's access to every
    workspace; uncaged, the real Docker socket (engine/sandbox_broker.py)."""
    return broker.walled(self, key, command)


def walled_for_home(self: "HermesEngine", home: Path) -> list[str]:
    """The wall's launcher (ends with "--") for a root or member home."""
    root = home.parent.parent if home.parent.name == "profiles" else home
    prefix = self.settings.profile_prefix
    workspace_id = root.name[len(prefix) :] if root.name.startswith(prefix) else root.name
    return self.walled(workspace_id, [])


def walled_cli(self: "HermesEngine", key: str, *args: str, timeout: float = 60) -> str:
    """Hermes's CLI for this profile, walled (a plugin's CLI command: Hermes
    imports the root's plugins to find it, hermes_cli/main.py
    _register_plugin_cli_commands)."""
    off_loop(" ".join(["hermes", *args[:1]]))
    return self.runner.run(
        self.walled(key, [self.settings.hermes_bin, *args]),
        timeout=timeout,
        env=self.hermes_env(key),
    )


def lock_dir(self: "HermesEngine", key: str) -> Path:
    """The root's own folder for Hermes's machine-wide gateway locks (Telegram
    token locks, host records): Hermes's HERMES_GATEWAY_LOCK_DIR (gateway/
    status.py _get_lock_dir), so no workspace's gateway reads or replaces
    another's in the shared ~/.local/state/hermes. In the root's temp folder:
    never in its backups (a lock is about one running process)."""
    return self.temp_dir(self.split(key)[0]) / "gateway-locks"


def browser_dir(self: "HermesEngine", key: str) -> Path:
    """The root's own folder for Hermes's browser engine (browser-harness, the
    Browser Use CLI bundled with Hermes: its daemons' sockets, spawn locks, logs
    and config). The harness reads BH_HOME (browser_harness/paths.py home_dir)
    and Hermes passes its process env to it (tools/browser_use_cli.py
    _base_subprocess_env); without it every workspace shares
    ~/.config/browser-harness, one "default" daemon for all of them, and the
    wall closes that folder so a walled browser_exec failed its first call. In
    the root's temp folder: its sockets need a short path, and like the gateway
    locks it is about running processes, never part of a backup."""
    return self.temp_dir(self.split(key)[0]) / "browser-harness"


def forbidden(self: "HermesEngine", agos_data: Path) -> tuple[Path, ...]:
    return (
        agos_data,
        self.settings.hermes_home,
        self.settings.roots_dir,
        self.settings.managed_home,
        *host_secret_dirs(self.settings.host_home),
    )


def temp_dir(self: "HermesEngine", workspace_id: str) -> Path:
    """The gateway's own temp folder (TMPDIR): ~/.agos-tmp/<10 chars>.

    Not /tmp: agos-core runs with systemd PrivateTmp, a gateway it starts
    shared that /tmp, and agos-core's restart (every update) deleted it under
    the still-running gateway (browser: "No such file or directory:
    /tmp/agent-browser-…"). Short, because Hermes puts the browser's socket in
    it and falls back to /tmp when the path is too long."""
    import hashlib

    name = hashlib.sha256(self.profile(workspace_id).encode()).hexdigest()[:10]
    path = self.settings.host_home / ".agos-tmp" / name
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


# ---- a Co-Founder runs as Hermes's own gateway service --------------------


def is_member(workspace_id: str) -> bool:
    """A team member's profile key (a workspace id never has `--`)."""
    return "--" in workspace_id
