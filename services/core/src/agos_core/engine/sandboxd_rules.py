"""What a workspace's gateway may ask Docker to create (engine/sandboxd.py).

Pure checks over a parsed /containers/create body and the workspace's policy:
image, labels (the broker stamps its own owner label; callers set hermes-* only),
binds (realpath inside the workspace's own folders), tmpfs, network, caps, security
options and every HostConfig field that could reach the host. Stdlib only, loaded
by the daemon as its sibling file (no agos_core import here).
"""

from __future__ import annotations

import json
import os
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path

PROFILE_LABEL = "hermes-profile"
AGENT_LABEL = "hermes-agent"
PROBE_LABEL = "agos-sandboxd-probe"
# Stamped by the broker on every container it creates: the workspace (profile) whose
# socket created it. Callers may set only hermes-* labels, so nobody else can.
OWNER_LABEL = "agos-sandboxd-owner"
# Hermes's own cap-adds (tools/environments/docker.py _BASE_SECURITY_ARGS +
# _PRIVDROP_CAP_ARGS); nothing beyond them is ever granted.
ALLOWED_CAPS = {"CHOWN", "DAC_OVERRIDE", "FOWNER", "SETUID", "SETGID"}
# Network modes Hermes's cgroup-limit probe may use (`docker run --rm <image> sleep 0`
# on the default network, mounting nothing, running nothing but `sleep 0`).
UNBOUND_NETWORKS = {"", "default", "bridge", "none"}
PROBE_CMD = ["sleep", "0"]
# Bind options that change nothing about WHAT is mounted.
_BIND_OPTIONS = {"ro", "rw", "z", "Z", "private", "rprivate", "nocopy", "consistent", "cached",
                 "delegated"}  # fmt: skip
_TMPFS_FLAGS = {"rw", "ro", "nosuid", "nodev", "noexec", "exec", "noatime"}
_TMPFS_VALUE = re.compile(r"(size=[0-9]+[kmgKMG]?|mode=[0-7]{3,4}|uid=[0-9]+|gid=[0-9]+)")
# Hermes names its sandboxes hermes-<hex> (docker.py _start_container); AGOS's own
# containers (agos-mcp-*) are never a name a gateway may take.
_NAME_RE = re.compile(r"^hermes-[A-Za-z0-9_.-]{1,64}$")
# Container-create top-level keys (Docker's container.Config + the two configs):
# anything else is refused when set.
_CREATE_KEYS = {
    "Hostname", "Domainname", "User", "AttachStdin", "AttachStdout", "AttachStderr",
    "ExposedPorts", "Tty", "OpenStdin", "StdinOnce", "Env", "Cmd", "Healthcheck",
    "ArgsEscaped", "Image", "Volumes", "WorkingDir", "Entrypoint", "NetworkDisabled",
    "MacAddress", "OnBuild", "Labels", "StopSignal", "StopTimeout", "Shell", "HostConfig",
    "NetworkingConfig",
}  # fmt: skip
# HostConfig keys that are resource/cosmetic knobs: any value is fine. Keys
# validated by name sit in validate_create; every OTHER key is refused when set.
_BENIGN_HOST_CONFIG = {
    "AutoRemove", "BlkioWeight", "ConsoleSize", "ContainerIDFile", "CpuCount", "CpuPercent",
    "CpuPeriod", "CpuQuota", "CpuRealtimePeriod", "CpuRealtimeRuntime", "CpuShares", "CpusetCpus",
    "CpusetMems", "Dns", "DnsOptions", "DnsSearch", "GroupAdd", "Init", "IOMaximumBandwidth",
    "IOMaximumIOps", "KernelMemory", "KernelMemoryTCP", "LogConfig", "Memory", "MemoryReservation",
    "MemorySwap", "MemorySwappiness", "NanoCpus", "OomScoreAdj", "PidsLimit", "ReadonlyRootfs",
    "ShmSize", "StorageOpt", "Ulimits",
}  # fmt: skip
_CHECKED_HOST_CONFIG = {
    "Binds", "Tmpfs", "NetworkMode", "CapAdd", "CapDrop", "SecurityOpt", "RestartPolicy",
    "ExtraHosts", "IpcMode", "CgroupnsMode", "Privileged", "PublishAllPorts",
}  # fmt: skip
_REFUSED_WHEN_SET = ("Devices", "DeviceRequests", "DeviceCgroupRules", "Links", "VolumesFrom",
                     "PortBindings", "Mounts", "CgroupParent", "Cgroup", "PidMode", "UTSMode",
                     "UsernsMode", "Annotations", "Sysctls", "OomKillDisable", "Isolation",
                     "Runtime", "VolumeDriver")  # fmt: skip
# Present at all (even []) = Docker's default /proc masks are replaced: refused.
_REFUSED_WHEN_PRESENT = ("MaskedPaths", "ReadonlyPaths")


@dataclass(frozen=True)
class Policy:
    """One workspace's rules, as engine/cage.py `policy` wrote them."""

    profile: str
    labels: frozenset[str]
    images: frozenset[str]
    networks: frozenset[str]
    binds_rw: tuple[str, ...]
    binds_ro: tuple[str, ...]
    # Containers created before the broker served this workspace (epoch seconds)
    # carry no owner label; only those may be adopted by their Hermes label.
    legacy_before: float = 0.0


POLICY_SUFFIX = ".policy.json"


def load_policy(path: Path) -> Policy:
    data = json.loads(path.read_text())
    return Policy(
        profile=path.name.removesuffix(POLICY_SUFFIX),
        labels=frozenset(str(x) for x in data.get("labels", [])),
        images=frozenset(str(x) for x in data.get("images", [])),
        networks=frozenset(str(x) for x in data.get("networks", [])),
        binds_rw=tuple(str(x) for x in data.get("binds_rw", [])),
        binds_ro=tuple(str(x) for x in data.get("binds_ro", [])),
        legacy_before=float(data.get("legacy_before") or 0.0),
    )


def _truthy(value: object) -> bool:
    """Set to something that matters: {} [] "" 0 False None and nests of them are not."""
    if isinstance(value, dict):
        return any(_truthy(v) for v in value.values())
    if isinstance(value, list):
        return any(_truthy(v) for v in value)
    return bool(value)


def _under(real: str, prefixes: tuple[str, ...]) -> bool:
    return any(real == p or real.startswith(p.rstrip("/") + "/") for p in prefixes)


def _container_path(path: str) -> bool:
    """An absolute, already-normal path inside the container."""
    return path.startswith("/") and posixpath.normpath(path) == path and "\\" not in path


def _bind_error(spec: object, policy: Policy) -> str | None:
    if not isinstance(spec, str):
        return f"bind {spec!r} is not a string"
    parts = spec.split(":")
    if len(parts) < 2 or len(parts) > 3 or not parts[0].startswith("/"):
        return f"bind {spec!r} is not host:container[:options]"
    if not _container_path(parts[1]):
        return f"bind target {parts[1]!r} is not a plain absolute path"
    options = parts[2].split(",") if len(parts) == 3 else []
    if bad := [o for o in options if o not in _BIND_OPTIONS]:
        return f"bind option {bad[0]!r} is refused"
    host = parts[0]
    if not Path(host).exists():  # Docker would create it, as root, anywhere
        return f"bind source does not exist: {host}"
    real = os.path.realpath(host)
    allowed = policy.binds_rw + policy.binds_ro if "ro" in options else policy.binds_rw
    if not _under(real, tuple(os.path.realpath(p) for p in allowed)):
        return f"bind source is not this workspace's: {host}"
    return None


def _canonical_bind(spec: str) -> str:
    """The checked bind with its source as the realpath that was checked, so a
    symlink above it re-pointed after the check can't move what Docker mounts."""
    host, _, rest = spec.partition(":")
    return f"{os.path.realpath(host)}:{rest}"


def _tmpfs_error(tmpfs: object) -> str | None:
    if not isinstance(tmpfs, dict):
        return "HostConfig.Tmpfs is not an object"
    for target, options in tmpfs.items():
        if not isinstance(target, str) or not _container_path(target) or target == "/":
            return f"tmpfs target {target!r} is not a plain absolute path"
        if not isinstance(options, str):
            return f"tmpfs options for {target} are not a string"
        for option in filter(None, options.split(",")):
            if option not in _TMPFS_FLAGS and not _TMPFS_VALUE.fullmatch(option):
                return f"tmpfs option {option!r} is refused"
    return None


def _folded_duplicate(value: object) -> str | None:
    """A key given twice once case is ignored, at any depth. Docker decodes JSON
    with Go's encoding/json, which matches field names case-insensitively and lets
    the LAST one win: `"HostConfig": {...}, "hostconfig": {"Privileged": true}`
    would be checked as the first and run as the second."""
    if isinstance(value, dict):
        seen: set[str] = set()
        for key, item in value.items():
            folded = str(key).casefold()
            if folded in seen:
                return str(key)
            seen.add(folded)
            if (found := _folded_duplicate(item)) is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            if (found := _folded_duplicate(item)) is not None:
                return found
    return None


def _strings(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def prepare_create(
    body: object, policy: Policy, name: str = "", also_images: frozenset[str] = frozenset()
) -> tuple[str | None, object]:
    """(why refused, the body to forward). The broker sets the labels that prove
    ownership: callers may set only hermes-* labels, every container gets the
    owner label of THIS socket's workspace, and a body with no sandbox labels at
    all is Hermes's cgroup probe (`docker run --rm <image> sleep 0`): it gets this
    workspace's label, so its own start/attach/wait pass the ownership check."""
    if not isinstance(body, dict):
        return "create body is not an object", body
    labels = body.get("Labels") or {}
    if not isinstance(labels, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in labels.items()
    ):
        return "Labels is not an object of strings", body
    if bad := sorted(k for k in labels if not k.startswith("hermes-")):
        return f"label {bad[0]!r} is not one a sandbox may set (hermes-* only)", body
    labels = dict(labels)
    if not labels.get(PROFILE_LABEL) and AGENT_LABEL not in labels:
        own = sorted(policy.labels)[:1]
        if not own:
            return "this workspace has no sandbox label", body
        labels.update({PROFILE_LABEL: own[0], PROBE_LABEL: "1"})
    labels[OWNER_LABEL] = policy.profile
    body = {**body, "Labels": labels}
    if name and not _NAME_RE.match(name):
        return f"container name {name!r} is not a sandbox name (hermes-*)", body
    why = validate_create(body, policy, also_images)
    host = body.get("HostConfig")
    if why is None and isinstance(host, dict) and host.get("Binds"):
        body["HostConfig"] = {**host, "Binds": [_canonical_bind(b) for b in host["Binds"]]}
    return why, body


def _user_error(value: object) -> str | None:
    """Why a create's or an exec's User is refused (review L6): the sandbox runs as
    the image's own unprivileged `agent`, never root. Allowed: none (the image's
    USER), `agent`, or this broker's own uid[:gid] (what Hermes sends with
    docker_run_as_host_user; the image's agent is built with those ids,
    scripts/build-sandbox.sh)."""
    if value is None or value == "":
        return None
    allowed = {"agent", "agent:agent"}
    if os.getuid() != 0:
        allowed |= {str(os.getuid()), f"{os.getuid()}:{os.getgid()}"}
    if not isinstance(value, str) or value not in allowed:
        return f"User {value!r} is refused: the sandbox runs as the image's own agent"
    return None


def _fields_error(body: dict[str, object]) -> str | None:
    """Why a create body's top-level fields are refused: a name given twice (Docker
    folds case), a field that is no sandbox option, or a User other than the agent."""
    if (twice := _folded_duplicate(body)) is not None:
        return f"field {twice!r} is given twice (Docker reads names case-insensitively)"
    if bad := sorted(k for k, v in body.items() if k not in _CREATE_KEYS and _truthy(v)):
        return f"create field {bad[0]!r} is not a sandbox option"
    return _user_error(body.get("User"))


def validate_create(
    body: object, policy: Policy, also_images: frozenset[str] = frozenset()
) -> str | None:
    """Why this /containers/create body is refused, or None when it is exactly a
    sandbox this workspace may run. `also_images`: other names the broker resolved
    to the very image id of an allowed image."""
    if not isinstance(body, dict):
        return "create body is not an object"
    if (why := _fields_error(body)) is not None:
        return why
    if body.get("Image") not in policy.images | also_images:
        return f"image {body.get('Image')!r} is not this workspace's sandbox image"
    volumes = body.get("Volumes")
    # Any ENTRY is an anonymous volume, even {"path": {}}: refused.
    if (len(volumes) if isinstance(volumes, (dict, list, str)) else bool(volumes)) != 0:
        return "Volumes (anonymous volumes) are refused"
    labels = body.get("Labels") or {}
    if not isinstance(labels, dict):
        return "Labels is not an object"
    if labels.get(PROFILE_LABEL) not in policy.labels:
        return f"label {PROFILE_LABEL}={labels.get(PROFILE_LABEL)!r} is not this workspace's"
    if labels.get(OWNER_LABEL, policy.profile) != policy.profile:
        return f"label {OWNER_LABEL} names another workspace"
    probe = labels.get(PROBE_LABEL) == "1"
    if labels.get(AGENT_LABEL) != "1" and not probe:
        return f"missing label {AGENT_LABEL}=1"
    host = body.get("HostConfig") or {}
    if not isinstance(host, dict):
        return "HostConfig is not an object"
    for key in ("Privileged", "PublishAllPorts", *_REFUSED_WHEN_SET):
        value = host.get(key)
        # A present-but-empty container ({} [] "") is Docker's default; any ENTRY
        # matters, even an "empty" one (PortBindings {"80/tcp": [{}]} publishes).
        if len(value) if isinstance(value, (dict, list, str)) else bool(value):
            return f"HostConfig.{key} is refused"
    for key in _REFUSED_WHEN_PRESENT:
        if host.get(key) is not None:
            return f"HostConfig.{key} is refused"
    if host.get("IpcMode") not in (None, "", "private", "none", "shareable"):
        return "HostConfig.IpcMode is refused"
    if host.get("CgroupnsMode") not in (None, "", "private"):
        return "HostConfig.CgroupnsMode is refused"
    for key in ("CapAdd", "CapDrop", "SecurityOpt", "ExtraHosts", "Binds"):
        if host.get(key) is not None and not _strings(host.get(key)):
            return f"HostConfig.{key} is not a list of strings"
    for cap in host.get("CapAdd") or []:
        if cap.upper().removeprefix("CAP_") not in ALLOWED_CAPS:
            return f"CapAdd {cap!r} is beyond the sandbox set"
    for opt in host.get("SecurityOpt") or []:
        if opt not in ("no-new-privileges", "no-new-privileges:true", "no-new-privileges=true"):
            return f"SecurityOpt {opt!r} is refused"
    restart = host.get("RestartPolicy") or {}
    if not isinstance(restart, dict) or set(restart) - {"Name", "MaximumRetryCount"}:
        return "RestartPolicy has a field beyond Name/MaximumRetryCount"
    if restart.get("Name") not in (None, "", "no"):
        return "RestartPolicy is refused"
    for extra in host.get("ExtraHosts") or []:
        if extra != "host.docker.internal:host-gateway":
            return f"ExtraHosts {extra!r} is refused"
    if host.get("Tmpfs") is not None and (why := _tmpfs_error(host["Tmpfs"])):
        return why
    binds = host.get("Binds") or []
    for spec in binds:
        if (why := _bind_error(spec, policy)) is not None:
            return why
    if probe:
        if binds or _truthy(host.get("Tmpfs")) or _truthy(body.get("Entrypoint")):
            return "the cgroup probe mounts nothing and keeps the image's entrypoint"
        if body.get("Cmd") != PROBE_CMD or host.get("AutoRemove") is not True:
            return "an unlabelled container may only be Hermes's `--rm ... sleep 0` probe"
    networking = body.get("NetworkingConfig") or {}
    if not isinstance(networking, dict) or set(networking) - {"EndpointsConfig"}:
        return "NetworkingConfig has a field beyond EndpointsConfig"
    endpoints = networking.get("EndpointsConfig") or {}
    if not isinstance(endpoints, dict):
        return "NetworkingConfig.EndpointsConfig is not an object"
    networks = {str(host.get("NetworkMode") or ""), *(str(k) for k in endpoints)}
    allowed_nets = policy.networks | (UNBOUND_NETWORKS if probe else set())
    if bad_nets := networks - allowed_nets - ({""} if endpoints else set()):
        return f"network {sorted(bad_nets)[0]!r} is not this workspace's"
    for key, value in host.items():
        if key in _BENIGN_HOST_CONFIG or key in _CHECKED_HOST_CONFIG or not _truthy(value):
            continue
        return f"HostConfig.{key} is not a sandbox option"
    return None


def validate_exec(body: object) -> str | None:
    if not isinstance(body, dict):
        return "exec body is not an object"
    if (twice := _folded_duplicate(body)) is not None:
        return f"field {twice!r} is given twice (Docker reads names case-insensitively)"
    # Go matches "privileged" / "PRIVILEGED" to Privileged too.
    if any(str(k).casefold() == "privileged" and _truthy(v) for k, v in body.items()):
        return "Privileged exec is refused"
    for key, value in body.items():
        if str(key).casefold() == "user" and (why := _user_error(value)) is not None:
            return why
    return None
