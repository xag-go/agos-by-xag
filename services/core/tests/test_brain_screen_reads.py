"""The Brain tab (skills.disabled) and the Screen tab (agent.disabled_toolsets)
read the profile's setting as Hermes reads it (engine.as_hermes_reads: its
config.yaml with the managed scope on top), without starting Hermes's CLI on
every open."""

from __future__ import annotations

from typing import Any

from test_library import env, ws  # noqa: F401 - fixture


def _config_gets(runner: Any) -> list[list[str]]:
    return [list(c) for c in runner.calls if "config" in c and "get" in c]


def test_brain_and_screen_open_without_hermes_cli(env: Any) -> None:  # noqa: F811
    client, _core, runner, _home = env
    a = ws(client, "Alpha")
    runner.calls.clear()
    assert client.get(f"/workspaces/{a}/brain").status_code == 200
    assert client.get(f"/workspaces/{a}/screen").status_code == 200
    assert _config_gets(runner) == []
