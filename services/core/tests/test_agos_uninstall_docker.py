"""`agos uninstall` removes every container AGOS's workspaces left, Hermes's own too.

Hermes names the sandbox containers it starts `hermes-<hex>`, not `agos-*`: before this
fix uninstall left them running (workspace files mounted) and the workspace network could
not be removed. The function under test is cut out of deploy/agos and run against a fake
`docker` that keeps containers, networks and images in a JSON file.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(not shutil.which("bash"), reason="needs bash")

BASH = shutil.which("bash") or "/bin/bash"
AGOS = Path(__file__).resolve().parents[3] / "deploy" / "agos"

FAKE_DOCKER = r'''#!/usr/bin/env python3
"""A fake docker: ps -aq --filter, rm -f, network ls/rm, image rm."""
import json, os, sys
state_file = os.environ["FAKE_DOCKER_STATE"]
st = json.load(open(state_file))
args = sys.argv[1:]
with open(os.environ["FAKE_DOCKER_STATE"] + ".calls", "a") as log:
    log.write(" ".join(args) + "\n")

def filters(rest):
    out = []
    for i, a in enumerate(rest):
        if a == "--filter":
            k, v = rest[i + 1].split("=", 1)
            out.append((k, v))
    return out

def save():
    json.dump(st, open(state_file, "w"))

if args[:1] == ["ps"]:
    for c in st["containers"]:
        ok = True
        for k, v in filters(args[1:]):
            if k == "name": ok &= v in c["name"]
            elif k == "network": ok &= c["network"] == v
            elif k == "ancestor": ok &= c["image"] == v
        if ok:
            print(c["id"])
elif args[:2] == ["rm", "-f"]:
    gone = set(args[2:])
    st["containers"] = [c for c in st["containers"] if c["id"] not in gone]
    save()
elif args[:2] == ["network", "ls"]:
    for n in st["networks"]:
        if all(v in n for k, v in filters(args[2:]) if k == "name"):
            print(n)
elif args[:2] == ["network", "rm"]:
    for n in args[2:]:
        if any(c["network"] == n for c in st["containers"]):
            print(f"error while removing network: network {n} has active endpoints", file=sys.stderr)
            sys.exit(1)
    st["networks"] = [n for n in st["networks"] if n not in args[2:]]
    save()
elif args[:2] == ["image", "rm"]:
    if any(c["image"] in args[2:] for c in st["containers"]):
        sys.exit(1)
    st["images"] = [i for i in st["images"] if i not in args[2:]]
    save()
'''


def _function(name: str) -> str:
    text = AGOS.read_text()
    m = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", text, re.S | re.M)
    assert m, f"{name} not found in deploy/agos"
    return m.group(0)


def _run(tmp_path: Path, state: dict[str, list[Any]]) -> tuple[dict[str, list[Any]], str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    state_file = tmp_path / "docker.json"
    state_file.write_text(json.dumps(state))
    script = (
        "set -euo pipefail\n" + _function("remove_docker_leftovers") + "remove_docker_leftovers\n"
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_DOCKER_STATE": str(state_file),
    }
    done = subprocess.run(  # noqa: S603 - our own test script
        [BASH, "-c", script], env=env, capture_output=True, text=True, timeout=30, check=False
    )
    assert done.returncode == 0, done.stderr
    return json.loads(state_file.read_text()), done.stderr


def _used_workspace() -> dict[str, list[Any]]:
    return {
        "containers": [
            # Hermes's sandbox for the workspace: its own name, AGOS's network and image.
            {
                "id": "c1",
                "name": "hermes-354cacad",
                "network": "agos-net-shop",
                "image": "agos-sandbox:1",
            },
            {
                "id": "c2",
                "name": "agos-docker-proxy-shop",
                "network": "agos-net-shop",
                "image": "proxy",
            },
            # A browser sandbox Hermes started on the default network, from the desktop image.
            {
                "id": "c3",
                "name": "hermes-9f0e1d2c",
                "network": "bridge",
                "image": "agos-sandbox:desktop",
            },
            # Not AGOS's: stays.
            {"id": "c9", "name": "postgres", "network": "bridge", "image": "postgres:16"},
        ],
        "networks": ["agos-net-shop", "bridge"],
        "images": ["agos-sandbox:1", "agos-sandbox:desktop", "postgres:16"],
    }


def test_uninstall_removes_hermess_sandbox_containers_and_the_workspace_network(
    tmp_path: Path,
) -> None:
    state, _ = _run(tmp_path, _used_workspace())
    assert [c["name"] for c in state["containers"]] == ["postgres"]
    assert state["networks"] == ["bridge"]
    assert state["images"] == ["postgres:16"]


def test_uninstall_with_no_docker_leftovers_is_quiet(tmp_path: Path) -> None:
    state, err = _run(tmp_path, {"containers": [], "networks": [], "images": []})
    assert state == {"containers": [], "networks": [], "images": []}
    assert err == ""
    calls = (tmp_path / "docker.json.calls").read_text()
    assert "rm -f" not in calls
    assert "network rm" not in calls


def test_uninstall_calls_the_docker_cleanup() -> None:
    body = _function("cmd_uninstall")
    assert "remove_docker_leftovers" in body
