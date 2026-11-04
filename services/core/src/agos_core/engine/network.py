"""Network isolation for workspace sandboxes (step 6b).

- One internal Docker network per workspace (`agos-net-<profile>`, `--internal`: no
  route to the host, the LAN, Tailscale or the internet).
- One shared AGOS egress proxy container (`agos-egress`) on the normal bridge and on
  every workspace network: the only way out, public internet only.
- The sandbox's Hermes config gets `--network=<internal net>` plus HTTP(S)_PROXY.

Fail closed: if the proxy can't run, sandboxes still get the internal network
(no internet at all) rather than the default bridge.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

# A second AGOS on the same machine (`agos staging`) runs its own proxy under its own
# name, so it never replaces or rewires live's (AGOS_EGRESS_NAME, set by the staging
# units only). Anything that isn't a plain Docker name falls back to the default.
_NAME = os.environ.get("AGOS_EGRESS_NAME", "")
PROXY_NAME = _NAME if re.fullmatch(r"agos-[a-z0-9-]{1,40}", _NAME) else "agos-egress"
PROXY_PORT = 8888
LABEL = "agos-egress=1"
NO_PROXY = "localhost,127.0.0.1"


def network_name(profile: str) -> str:
    return f"agos-net-{profile}"


def proxy_url() -> str:
    return f"http://{PROXY_NAME}:{PROXY_PORT}"


def sandbox_settings(profile: str) -> dict[str, str]:
    """Extra `hermes config set` pairs for a sandbox behind the proxy."""
    url = proxy_url()
    env = {
        "HTTP_PROXY": url,
        "HTTPS_PROXY": url,
        "http_proxy": url,
        "https_proxy": url,
        "NO_PROXY": NO_PROXY,
        "no_proxy": NO_PROXY,
    }
    return {
        "terminal.docker_extra_args": json.dumps([f"--network={network_name(profile)}"]),
        "terminal.docker_env": json.dumps(env),
    }


@dataclass(frozen=True)
class NetworkPlan:
    network: str
    proxy: str
    script: Path


def plan(profile: str, script: Path) -> NetworkPlan:
    return NetworkPlan(network_name(profile), PROXY_NAME, script)
