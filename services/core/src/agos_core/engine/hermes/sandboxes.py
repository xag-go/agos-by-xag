"""The profile's Docker sandboxes Hermes starts: find, inspect, check against the
grants, remove, and which one holds the workspace's screen.

Owns: Every `docker` call on a profile's own containers, and the container key (label)
that keeps two workspaces' sandboxes apart.

Must not: Decide the mounts (engine/rules.py) or grab the screen (screen_jpeg stays in the
facade: it runs _run_bytes, which tests replace on engine/hermes).

Part of engine/hermes (HermesEngine binds these functions as its methods).
"""

import contextlib
import hashlib
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agos_core.engine.loop_guard import off_loop
from agos_core.engine.rules import SCREEN_TOOLSETS, Mount, SandboxCheck, check_sandbox_mounts
from agos_core.hermes_gateway.errors import EngineError

if TYPE_CHECKING:
    from agos_core.engine.hermes import HermesEngine

__all__ = [
    "_clear_sandbox_dirs",
    "_docker",
    "_sandbox_of",
    "has_screen",
    "remove_sandboxes",
    "sandbox_address",
    "sandbox_kill",
    "sandbox_label",
    "sandbox_label_of",
    "sandbox_mounts",
    "sandboxes",
    "screen_container",
    "verify",
]


def sandbox_label_of(name: str) -> str:
    """The container key (and so the `hermes-profile` label) of AGOS's profile `name`."""
    clean = re.sub(r"[^A-Za-z0-9_.-]", "_", name)[:63] or "unknown"
    return f"{clean[:50]}-{hashlib.sha256(name.encode()).hexdigest()[:12]}"


def sandbox_label(self: "HermesEngine", key: str) -> str:
    """The `hermes-profile` label Hermes gives this profile's sandboxes. In a root
    every Co-Founder is "default", so AGOS gives each profile its own container key
    (`terminal.docker_shared_container_key` = AGOS's name) and Hermes labels with
    it: no two workspaces' sandboxes can ever be taken for each other."""
    return sandbox_label_of(self.profile(key))


def has_screen(self: "HermesEngine", workspace_id: str) -> bool:
    """Browser or computer use is on in Hermes's own config (not in the profile's
    `agent.disabled_toolsets`): Hermes then gives the agent its screen.

    Read as Hermes reads it (as_hermes_reads: the profile's config.yaml with the
    managed scope on top, kept while those files are unchanged), so no Hermes
    starts per page; unset is Hermes's default [] (hermes_cli/config_defaults.py),
    like `hermes config get`, which is still asked when that read fails."""
    try:
        config = self.as_hermes_reads([self.profile_home(workspace_id)])
        cfg = config.get(str(self.profile_home(workspace_id)))
        if not isinstance(cfg, dict):
            raise EngineError("no read of the profile's config")
        agent = cfg.get("agent")
        off: Any = agent.get("disabled_toolsets", []) if isinstance(agent, dict) else []
    except (EngineError, OSError, ValueError):
        try:
            raw = self._hermes(workspace_id, "config", "get", "agent.disabled_toolsets", "--json")
            off = json.loads(raw or "[]")
        except (EngineError, OSError, ValueError):
            return False
    if not isinstance(off, list):
        return False
    return any(name not in off for name in SCREEN_TOOLSETS)


# ---- sandboxes ---------------------------------------------------


def _docker(self: "HermesEngine", *args: str, timeout: float = 60) -> str:
    off_loop(" ".join(["docker", *args[:1]]))
    return self.runner.run([self.settings.docker_bin, *args], timeout=timeout)


def sandboxes(self: "HermesEngine", workspace_id: str) -> list[str]:
    out = self._docker(
        "ps",
        "-aq",
        "--filter",
        "label=hermes-agent=1",
        "--filter",
        f"label=hermes-profile={self.sandbox_label(workspace_id)}",
    )
    return [line for line in out.split() if line]


def _sandbox_of(self: "HermesEngine", profile: str) -> str | None:
    """The running sandbox Hermes started for AGOS's profile `profile`."""
    try:
        out = self._docker(
            "ps",
            "-q",
            "--filter",
            "label=hermes-agent=1",
            "--filter",
            f"label=hermes-profile={sandbox_label_of(profile)}",
            "--filter",
            "status=running",
        )
    except EngineError:
        return None
    found = [line for line in out.split() if line]
    return found[0] if found else None


def sandbox_address(self: "HermesEngine", profile: str) -> str | None:
    """Where this machine reaches a service inside the profile's sandbox: the
    container's address on its network (a card's preview, step 59)."""
    cid = self._sandbox_of(profile)
    if cid is None:
        return None
    try:
        out = self._docker(
            "inspect",
            "-f",
            "{{range $k, $v := .NetworkSettings.Networks}}{{$v.IPAddress}} {{end}}",
            cid,
        )
    except EngineError:
        return None
    found = [a for a in out.split() if a]
    return found[0] if found else None


def sandbox_kill(self: "HermesEngine", profile: str, pid: int) -> None:
    """TERM to a process Hermes started inside the profile's sandbox (its pid
    there); nothing when the sandbox is gone."""
    cid = self._sandbox_of(profile)
    if cid is not None:
        with contextlib.suppress(EngineError):
            self._docker("exec", cid, "kill", "-TERM", str(int(pid)))


# ---- the workspace's screen (browser / computer use) --------------------


def screen_container(self: "HermesEngine", workspace_id: str) -> str | None:
    """The sandbox Hermes started this profile's screen in: Hermes's own record
    (`<home>/bot-desktop/sandbox.json`, tools/bot_desktop/sandbox_host.py), kept
    only while that screen is up. None when Hermes has no screen running, or
    when the record names a container that isn't this workspace's sandbox."""
    record = self.profile_home(workspace_id) / "bot-desktop" / "sandbox.json"
    try:
        found = json.loads(record.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    container = str(found.get("container") or "") if isinstance(found, dict) else ""
    if not container:
        return None
    # Only ever look into this workspace's own sandbox.
    try:
        mine = self.sandboxes(workspace_id)
    except EngineError:
        return None
    return next(
        (cid for cid in mine if container.startswith(cid) or cid.startswith(container)),
        None,
    )


def remove_sandboxes(self: "HermesEngine", workspace_id: str) -> int:
    ids = self.sandboxes(workspace_id)
    if ids:
        self._docker("rm", "-f", *ids, timeout=120)
    return len(ids)


def sandbox_mounts(self: "HermesEngine", container_id: str) -> list[tuple[str, str, bool]]:
    raw = self._docker("inspect", "--format", "{{json .Mounts}}", container_id)
    return [
        (str(m.get("Source", "")), str(m.get("Destination", "")), bool(m.get("RW")))
        for m in json.loads(raw) or []
        if m.get("Type") == "bind"
    ]


def verify(
    self: "HermesEngine",
    workspace_id: str,
    mounts: list[Mount],
    shared_skills: tuple[Path, ...] = (),
) -> list[tuple[str, SandboxCheck]]:
    """Checks every live sandbox of this workspace against the grants."""
    home = self.profile_home(workspace_id)
    return [
        (
            cid,
            check_sandbox_mounts(
                self.sandbox_mounts(cid), mounts, profile_home=home, shared_skills=shared_skills
            ),
        )
        for cid in self.sandboxes(workspace_id)
    ]


def _clear_sandbox_dirs(self: "HermesEngine", workspace_id: str) -> None:
    """On Linux, Docker creates missing bind-mount folders under the profile's
    `sandboxes/` as root, so neither Hermes nor AGOS can delete them. A one-shot
    container that mounts ONLY that folder empties it (nothing else visible)."""
    folder = self.profile_home(workspace_id) / "sandboxes"
    if not folder.is_dir():
        return
    with contextlib.suppress(EngineError):
        self._docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            "0",
            "--entrypoint",
            "sh",
            "-v",
            f"{folder.resolve()}:/clear",
            self.settings.sandbox_image,
            "-c",
            "rm -rf /clear/* /clear/.[!.]* /clear/..?* 2>/dev/null; true",
            timeout=120,
        )
