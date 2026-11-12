"""What a workspace's Hermes profile is allowed to see and do (ADR 0010).

Pure functions: no Docker, no Hermes. agos-core is the only writer of a profile's
config, and everything it writes comes from here, so the rules are tested once.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from agos_core.domain.workspace import require_workspace_id

WORKSPACE_MOUNT = "/workspace"
# The team's agents and automations shown in playbooks/ (read-only). Skills are not
# there: agents read them natively (Hermes's skills, from the shared folders).
TEAM_FOLDERS = ("agents", "automations")
SHARED_ROOT = "/shared"

# Off unless the owner turns them on for a workspace (Capabilities → Tools).
# vision/video: with the docker backend Hermes reads a picture or video INSIDE the
# sandbox (only host media caches are read on the host; .env/auth.json refused),
# so they see /workspace and the shared folders, nothing else.
OPTIONAL_TOOLSETS: tuple[str, ...] = (
    "code_execution",
    "delegation",
    "image_gen",
    "tts",
    "vision",
    "video",
    "browser",
    "computer_use",
)
# Tools that use the workspace's screen (Hermes's Bot Desktop, placed INSIDE the
# sandbox): the Screen tab shows it while one of them is on in Hermes's config.
SCREEN_TOOLSETS: tuple[str, ...] = ("browser", "computer_use")
# Never on: they reach the host or other accounts. (Hermes's Kanban tools are
# always on: every profile works its own workspace's board, and a sandbox setup
# that turned them off left the Co-Founder unable to work its cards.)
LOCKED_TOOLSETS: tuple[str, ...] = (
    "connections",
    "homeassistant",
    "spotify",
)
DISABLED_TOOLSETS: tuple[str, ...] = LOCKED_TOOLSETS + OPTIONAL_TOOLSETS

# Characters that would change the meaning of a Docker volume spec
# ("host:container[:ro]") or of the YAML/JSON we write.
_UNSAFE_IN_MOUNT = re.compile(r"[:,\n\r\x00]")
_SHARE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


class MountRefusedError(ValueError):
    """The message is safe to show to the owner."""


@dataclass(frozen=True)
class Mount:
    host_path: Path
    container_path: str
    read_only: bool

    def spec(self) -> str:
        return f"{self.host_path}:{self.container_path}{':ro' if self.read_only else ''}"


@dataclass(frozen=True)
class Grant:
    """A folder the owner added: `/shared/<name>`, read or read-write."""

    name: str
    host_path: str
    access: Literal["read", "read-write"]


def profile_name(prefix: str, workspace_id: str) -> str:
    """Hermes profile for a workspace. Hermes allows [a-z0-9_-], up to 64 chars;
    a long id is shortened with a hash so two ids never share a profile."""
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,15}", prefix):
        raise ValueError("invalid profile prefix")
    workspace_id = require_workspace_id(workspace_id)
    name = f"{prefix}{workspace_id}"
    if len(name) <= 64:
        return name
    digest = hashlib.sha256(workspace_id.encode()).hexdigest()[:10]
    return f"{prefix}{workspace_id[: 64 - len(prefix) - 11].rstrip('-')}-{digest}"


def _check_host_path(path: Path, *, forbidden: tuple[Path, ...]) -> Path:
    if not path.is_absolute():
        raise MountRefusedError("a mounted folder must be a full path")
    if _UNSAFE_IN_MOUNT.search(str(path)):
        raise MountRefusedError("folder paths with ':' or ',' can't be shared with the agent")
    real = path.resolve()
    if real == Path(real.anchor):
        raise MountRefusedError("the whole disk can't be shared with the agent")
    for private in forbidden:
        private_real = private.resolve()
        if real == private_real or private_real in real.parents or real in private_real.parents:
            raise MountRefusedError("this folder overlaps AGOS's or the engine's private data")
    return real


def grants_in(volumes: list[str]) -> list[Grant]:
    """The owner's added folders as Hermes holds them: the `/shared/<name>` entries of
    a profile's `terminal.docker_volumes` (`host:/shared/<name>[:mode]`, Docker's
    own spec; hermes_cli/config_defaults.py, tools/environments/docker.py). Read and
    write only when the spec says so (no mode or `rw`); any other mode is read only.
    Every entry still goes through build_mounts' checks before it is mounted again."""
    out: dict[str, Grant] = {}
    for spec in volumes:
        parts = str(spec).split(":")
        mode = ""
        if len(parts) >= 3 and parts[-1] and "/" not in parts[-1]:
            mode = parts.pop()
        if len(parts) < 2:
            continue
        host, target = ":".join(parts[:-1]), parts[-1]
        prefix = f"{SHARED_ROOT}/"
        name = target[len(prefix) :] if target.startswith(prefix) else ""
        if not host or not _SHARE_NAME.fullmatch(name) or name in out:
            continue
        access: Literal["read", "read-write"] = "read-write" if mode in ("", "rw") else "read"
        out[name] = Grant(name=name, host_path=host, access=access)
    return [out[n] for n in sorted(out)]


def host_secret_dirs(home: Path) -> tuple[Path, ...]:
    """Host folders that hold keys or control Docker. A grant may never be one of
    them, inside one, or contain one (so adding the home folder is refused)."""
    return (
        Path("/var/run/docker.sock"),
        Path("/run/docker.sock"),
        home / ".docker",
        home / ".ssh",
        home / ".gnupg",
        home / ".aws",
        home / ".kube",
        home / ".config" / "gh",
        # The one AI login every workspace shares (ADR 0020), and Codex CLI's.
        home / ".claude",
        home / ".codex",
    )


def build_mounts(
    files_dir: Path,
    grants: list[Grant],
    *,
    workspaces_dir: Path,
    forbidden: tuple[Path, ...],
    files_read_only: bool = False,
) -> list[Mount]:
    """The complete list of what the sandbox sees. Nothing else is ever mounted:
    no home, no Docker socket, no other workspace's private data.

    `forbidden` = AGOS's data dir, Hermes's home and `host_secret_dirs()`. The
    workspace's own folder is the one path allowed inside AGOS's data dir."""
    own = files_dir.resolve()
    if workspaces_dir.resolve() not in own.parents:
        raise MountRefusedError("the workspace folder is outside AGOS's workspaces")
    # A member's own profile sees the workspace's files read-only.
    mounts = [Mount(own, WORKSPACE_MOUNT, files_read_only)]
    seen = {WORKSPACE_MOUNT}
    for grant in grants:
        if not _SHARE_NAME.fullmatch(grant.name):
            raise MountRefusedError("invalid shared folder name")
        target = f"{SHARED_ROOT}/{grant.name}"
        if target in seen:
            raise MountRefusedError("two folders with the same name")
        seen.add(target)
        host = _check_host_path(Path(grant.host_path), forbidden=forbidden)
        mounts.append(Mount(host, target, grant.access != "read-write"))
    # What the team uses (agents, automations) is shown in playbooks/ and
    # changed only through AGOS (a card): read-only over the writable workspace
    # (Docker mounts a parent before the folders inside it).
    for kind in TEAM_FOLDERS:
        folder = own / "playbooks" / kind
        folder.mkdir(parents=True, exist_ok=True)
        mounts.append(Mount(folder, f"{WORKSPACE_MOUNT}/playbooks/{kind}", True))
    return mounts


def screen_image(image: str) -> str:
    """The sandbox image with Hermes's desktop stack: `agos-sandbox:1` ->
    `agos-sandbox:desktop` (like Hermes's own default, `hermes-sandbox:desktop`)."""
    return f"{image.rsplit(':', 1)[0]}:desktop"


def profile_config(
    *,
    image: str,
    mounts: list[Mount],
    network: dict[str, str] | None = None,
    model: tuple[str, str, str] | None = None,
    container_key: str = "",
    zone: str = "",
) -> dict[str, str]:
    """`hermes config set <key> <value>` pairs, applied in this order.
    `zone`: the owner's timezone (Hermes's `timezone`, actions/owner_time.py). The
    sandbox gets it as `TZ`, so `date` there says his time: Hermes's docker backend
    passes only `terminal.docker_env` into the container, not `timezone`.
    `container_key` (a workspace on its own Hermes root, ADR 0020): its profiles'
    sandboxes are labelled with AGOS's own name, not Hermes's ("default" in every
    root), and the root's one gateway serves its members (no standalone shim).
    The loop detector, run budget, fallback chain, timeouts and `timezone` are
    never here: they are one value in Hermes's managed scope
    (actions/hermes_managed.py), which refuses them per profile.
    Values are JSON so Hermes reads lists and booleans exactly. `network` (step 6b)
    puts the sandbox on its internal network behind AGOS's egress proxy.

    Every sandbox runs the image with the desktop stack, as Hermes's own default
    sandbox does (`nousresearch/hermes-sandbox:desktop`): Hermes starts the screen
    only when browser or computer use needs it (`bot_desktop.placement: terminal`
    starts it on first use, inside the sandbox) and stops it after
    `bot_desktop.idle_stop_minutes` (Hermes's own setting). Turning those tools on
    or off is only Hermes's `agent.disabled_toolsets`: the sandbox stays."""
    config = {
        "terminal.backend": "docker",
        "terminal.docker_image": screen_image(image),
        "terminal.docker_mount_cwd_to_workspace": "false",
        "terminal.docker_run_as_host_user": "false",
        "terminal.docker_forward_env": "[]",
        "terminal.docker_env": "{}",
        "terminal.docker_extra_args": "[]",
        "terminal.cwd": WORKSPACE_MOUNT,
        "terminal.credential_files": "[]",
        "terminal.docker_volumes": json.dumps([m.spec() for m in mounts]),
        "agent.disabled_toolsets": json.dumps(list(DISABLED_TOOLSETS)),
        # Every risky command reaches the owner ("Ask me"); Hermes's "smart" mode
        # would let its own model approve some. Only a new profile starts here:
        # afterwards it is the owner's access switch, Hermes's own setting
        # (actions/access.py), never reset by a sandbox sync.
        "approvals.mode": "manual",
        # No clock on the team's work (the owner's rule): nothing is cut for time.
        # Every Hermes timeout (a command waiting for his yes, a quiet run, a
        # question, a subagent, a long command...) is in `seeded_config`: a new
        # profile starts on the owner's values, and afterwards they are his
        # (General settings → Time limits), never reset here.
        # - Subagents have no step budget; the main agent already has none.
        # The loop detector and the owner's own limits (Workspace settings) stay his.
        # Each workspace's Hermes uses only the logins it holds itself (ADR 0020:
        # one login per root, made with Hermes's `hermes auth add` in that root),
        # never one it borrows from another program's file.
        "auth.adopt_external_logins": "false",
        # Hermes's own busy notes ("↪ Redirected current run…") reach him, as on his
        # own Hermes (`false` here hid them on Telegram too).
        "display.busy_ack_enabled": "true",
        "delegation.max_iterations": "1000000",
        # No ceiling on web searches or subagents per turn.
        "tool_loop_guardrails.loop_caps.max_web_searches": "0",
        "tool_loop_guardrails.loop_caps.max_subagents": "0",
        # A provider hiccup (5xx, overloaded, timeouts) is waited out, not a failed task.
        "agent.api_max_retries": "10",
        "agent.auto_recovery_cycles": "1000",
        "compression.max_attempts": "10",
        # Long chats are summarised like in Hermes (older turns compacted, nothing
        # lost from memory): at 200K tokens, not at half of a 1M window.
        "compression.threshold_tokens": "200000",
        # No character cap on memory (engine/identity.py MEMORY_LIMIT).
        "memory.memory_char_limit": "1000000",
        "memory.user_char_limit": "1000000",
        # Deep memory (Hermes's holographic fact store) next to MEMORY.md/USER.md.
        # Its database is $HERMES_HOME/memory_store.db, so each profile keeps its own.
        "memory.provider": "holographic",
        # One gateway per workspace, serving only its own profile (its API, its
        # Telegram bot). Without it Hermes may fold the profiles into one multiplexed
        # host, and this profile's gateway then drops its own API server.
        "gateway.standalone": "false" if container_key else "true",
        # Who hears his voice notes (stt.provider and its model) is one value for
        # every workspace in Hermes's managed scope (General settings → Voice notes,
        # actions/hermes_voice.py), never here.
        # Hermes doesn't post the transcript back in the chat (he knows what he said).
        "stt.echo_transcripts": "false",
        # Every message the agent reads carries the moment it was sent (Hermes's own
        # gateway.message_timestamps): a long-lived chat or topic still knows today's
        # date and time, not only the day its session started.
        "gateway.message_timestamps.enabled": "true",
    }
    # Browser and computer use run on the workspace's own screen, inside its
    # sandbox (same mounts, same network, same proxy), never on this machine:
    # "terminal" refuses instead of falling back to the host. The browser opens
    # on that screen, so the Screen tab shows what it does.
    config["bot_desktop.placement"] = "terminal"
    config["browser.headed"] = "true"
    if container_key:
        config["terminal.docker_shared_container_key"] = container_key
    config.update(seeded_config())
    if model:
        config.update(model_pairs(*model))
    if network:
        config.update(network)
    config["terminal.docker_env"] = sandbox_env(config["terminal.docker_env"], zone)
    return config


def sandbox_env(current: str, zone: str) -> str:
    """`terminal.docker_env` (JSON) with the owner's timezone as `TZ` (none: no TZ)."""
    try:
        env = json.loads(current or "{}")
    except ValueError:
        env = {}
    env = {str(k): str(v) for k, v in (env if isinstance(env, dict) else {}).items()}
    env.pop("TZ", None)
    if zone:
        env["TZ"] = zone
    return json.dumps(env)


def seeded_config() -> dict[str, str]:
    """What a NEW profile starts with and an existing one keeps as it has it
    (engine/hermes.py `apply` sets a key only while the profile doesn't have it):
    Hermes keeps the history, no auto-pruning of ended sessions (engine/history.py).
    (The timeouts are Hermes's managed scope: engine/time_limits.py owner_defaults.)"""
    from agos_core.engine import history

    return history.seeded_defaults()


def model_pairs(provider: str, model_id: str, effort: str) -> dict[str, str]:
    """A profile's default model, as Hermes keeps it (model.*, agent.reasoning_effort).
    Without it a fresh profile falls back to Hermes's template (OpenRouter) and
    anything not sending a model (gateway, cron) has no provider."""
    pairs = {
        "model.provider": provider,
        "model.default": model_id,
    }
    if effort:
        # None picked: Hermes's own default, which is no `agent.reasoning_effort` at all
        # (hermes_cli/config_defaults.py has none; hermes_cli/setup.py
        # _current_reasoning_effort reads "" = the model's own level).
        pairs["agent.reasoning_effort"] = effort
    if provider == "anthropic":
        pairs["model.base_url"] = "https://api.anthropic.com"
        pairs["model.api_mode"] = "anthropic_messages"
    else:
        pairs["model.base_url"] = ""
    return pairs


def expected_mounts(mounts: list[Mount]) -> set[tuple[str, str, bool]]:
    """What `docker inspect` must report for the sandbox (source, destination, rw)."""
    return {(str(m.host_path), m.container_path, not m.read_only) for m in mounts}


@dataclass(frozen=True)
class SandboxCheck:
    ok: bool
    missing: list[str]
    unexpected: list[str]


def check_sandbox_mounts(
    actual: list[tuple[str, str, bool]],
    mounts: list[Mount],
    *,
    profile_home: Path,
    shared_skills: tuple[Path, ...] = (),
) -> SandboxCheck:
    """Compares a sandbox's real mounts with the grants.

    Hermes adds its own mounts: read-only copies of this profile's skills and caches
    (under /root/.hermes) and, when persistence is on, a /root home. Those are
    accepted only if their source is inside **this** profile's home. Anything else
    — another profile, the host home, a socket, a writable extra — is unexpected."""
    want = expected_mounts(mounts)
    home = profile_home.resolve()
    missing = [
        f"{d} ({'rw' if rw else 'ro'})"
        for s, d, rw in sorted(want)
        if (s, d, rw) not in set(actual)
    ]
    unexpected: list[str] = []
    for source, dest, rw in actual:
        if (source, dest, rw) in want:
            continue
        src = Path(source)
        inside_profile = src == home or home in src.parents
        hermes_internal = dest == "/root" or dest.startswith("/root/.hermes/")
        if inside_profile and hermes_internal and (not rw or dest == "/root"):
            continue
        # The skill folders a profile reads (AGOS's own, the Brain's, a member's
        # workspace folder): Hermes mounts its skills.external_dirs read-only.
        shared = any(src == s or s in src.parents for s in (p.resolve() for p in shared_skills))
        if shared and not rw and dest.startswith("/root/.hermes/external_skills/"):
            continue
        unexpected.append(f"{dest} ({'rw' if rw else 'ro'})")
    return SandboxCheck(ok=not missing and not unexpected, missing=missing, unexpected=unexpected)
