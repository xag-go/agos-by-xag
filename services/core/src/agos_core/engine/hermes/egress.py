"""The workspace's internal Docker network and AGOS's egress proxy on it (step 6b).

Owns: Creating, joining and removing the workspace's internal network, and starting the
one egress proxy container (from engine/egress_proxy.py).

Must not: Decide the proxy's policy (engine/network.py, engine/egress_proxy.py) or touch the
profile's sandboxes (sandboxes.py).

Part of engine/hermes (HermesEngine binds these functions as its methods).
"""

import contextlib
from pathlib import Path
from typing import TYPE_CHECKING

from agos_core.engine import network as net
from agos_core.hermes_gateway.errors import EngineError

if TYPE_CHECKING:
    from agos_core.engine.hermes import HermesEngine

__all__ = [
    "ensure_network",
    "ensure_proxy",
    "remove_network",
]


# ---- network (step 6b) -----------------------------------------------


def ensure_network(self: "HermesEngine", workspace_id: str) -> None:
    """The workspace's internal network exists and the egress proxy is on it.
    Raises EngineError if Docker refuses (the caller fails closed)."""
    name = net.network_name(self.profile(workspace_id))
    existing = self._docker("network", "ls", "--filter", f"name=^{name}$", "--format", "{{.Name}}")
    if name not in existing.split():
        self._docker(
            "network",
            "create",
            "--internal",
            "--label",
            "agos-network=1",
            "--label",
            f"agos-profile={self.profile(workspace_id)}",
            name,
        )
    self.ensure_proxy()
    attached = self._docker(
        "inspect",
        "-f",
        "{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}",
        net.PROXY_NAME,
    )
    if name not in attached.split():
        self._docker("network", "connect", name, net.PROXY_NAME)


def ensure_proxy(self: "HermesEngine") -> None:
    running = self._docker(
        "ps", "-q", "--filter", f"name=^{net.PROXY_NAME}$", "--filter", "status=running"
    )
    if running.strip():
        return
    with contextlib.suppress(EngineError):
        self._docker("rm", "-f", net.PROXY_NAME)
    # This package sits in engine/, next to egress_proxy.py.
    script = Path(__file__).parent.with_name("egress_proxy.py").resolve()
    self._docker(
        "run",
        "-d",
        "--name",
        net.PROXY_NAME,
        "--restart",
        "unless-stopped",
        "--label",
        net.LABEL,
        "--network",
        "bridge",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--memory",
        "128m",
        "--pids-limit",
        "256",
        "-v",
        f"{script}:/agos/egress_proxy.py:ro",
        self.settings.sandbox_image,
        "python",
        "/agos/egress_proxy.py",
        timeout=180,
    )


def remove_network(self: "HermesEngine", workspace_id: str) -> None:
    name = net.network_name(self.profile(workspace_id))
    with contextlib.suppress(EngineError):
        self._docker("network", "disconnect", "-f", name, net.PROXY_NAME)
    with contextlib.suppress(EngineError):
        self._docker("network", "rm", name)
