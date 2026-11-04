"""The sandbox runs as the image's own unprivileged `agent` (review L6): the broker
refuses a container create, or an exec, that asks for another user (root above all).

What Hermes sends (tools/environments/docker.py): no User on create (AGOS pins
terminal.docker_run_as_host_user=false), or `<uid>:<gid>` of the gateway's own user
when that option is on, and never a user on exec. The image's `agent` is built with
the AGOS user's ids (scripts/build-sandbox.sh), so both stay allowed."""

from __future__ import annotations

import os
from pathlib import Path

from sandboxd_rig import _create_body, _policy

from agos_core.engine.sandboxd import validate_create, validate_exec

OWN = (f"{os.getuid()}:{os.getgid()}", str(os.getuid()))
ROOT = ("root", "0", "0:0", "root:root", "agent:root", f"{os.getuid()}:0", "nobody", "65534")


def test_a_sandbox_runs_only_as_the_images_agent(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    for user in ("", None, "agent", "agent:agent", *OWN):
        assert validate_create(_create_body(tmp_path, User=user), policy) is None, user
    for user in ROOT:
        why = validate_create(_create_body(tmp_path, User=user), policy)
        assert why is not None and "User" in why, user
    if os.getuid() != 0:
        assert validate_create(_create_body(tmp_path, User="0"), policy) is not None


def test_an_exec_runs_only_as_the_images_agent(tmp_path: Path) -> None:
    for user in ("", None, "agent", *OWN):
        assert validate_exec({"Cmd": ["true"], "User": user}) is None, user
    assert validate_exec({"Cmd": ["true"]}) is None
    for user in ROOT:
        why = validate_exec({"Cmd": ["true"], "User": user})
        assert why is not None and "User" in why, user
    # Docker reads JSON names case-insensitively: "user" is the same field.
    assert validate_exec({"Cmd": ["true"], "user": "root"}) is not None
