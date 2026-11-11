"""Testing an MCP server (locally or through Hermes).
Must not: change any setting; a test only reads.

Split out of agos_core.actions.library (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import re
import time

from pydantic import Field

from agos_core.actions import hermes_config as hc
from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.library.workspace_state import oauth_signed_in
from agos_core.context import Core
from agos_core.db import library as repo
from agos_core.db.records import Record
from agos_core.engine import library as lib
from agos_core.engine import mcp_errors
from agos_core.engine.hermes import EngineError
from agos_core.engine.library import LibraryError
from agos_core.hermes_gateway import cli as hermes_cli
from agos_core.security import mcp_address

__all__ = [
    "McpTest",
    "McpTool",
    "test_mcp",
]

# ---- MCP test ----------------------------------------------------------------------


class McpTool(Record):
    name: str
    description: str = ""


class McpTest(Record):
    ok: bool
    tools: list[McpTool] = Field(default_factory=list)
    error: str | None = None


def test_mcp(core: Core, item_id: int, workspace_id: str | None = None) -> McpTest:
    """Hermes's own `hermes mcp test` in the workspace's root: it connects with the
    entry and key (or sign-in) the root's Hermes has, and lists the tools."""
    row = repo.get_item(core.db, item_id)
    if row is None or row["kind"] != "mcp":
        raise NotFoundError("This MCP server")
    if workspace_id is not None and row["workspace_id"] != workspace_id:
        raise NotFoundError("This MCP server")  # another workspace's
    workspace_id = str(row["workspace_id"] or "") or None
    if core.engine is None:
        raise ActionError("The engine is off.", 409)
    here = hc.here(core, workspace_id) if workspace_id else hc.Here()
    entry = here.mcp.get(str(row["name"]))
    if entry is None:
        return McpTest(ok=False, error="This server isn't in the workspace any more.")
    if (why := mcp_address.entry_refusal(str(row["name"]), entry)) is not None:
        return McpTest(ok=False, error=f"Not tested: this server {why}.")
    definition = hc.definition_of(entry)
    try:
        lib.check_mcp(definition)
    except LibraryError as error:
        return McpTest(ok=False, error=str(error))
    assert workspace_id is not None
    if lib.is_local(definition):
        # It only runs inside the workspace's container: test it there.
        if not hc.is_on(entry):
            return McpTest(
                ok=False,
                error="Turn it on first: it runs in this workspace's own container.",
            )
        return _test_local(core, workspace_id, str(row["name"]))
    has_key = bool(here.keys.get(str(row["name"]))) or row["name"] in oauth_signed_in(
        core.engine.profile_home(workspace_id)
    )
    return _test_with_hermes(core, workspace_id, str(row["name"]), has_key=has_key)


_TOOL_LINE = re.compile(r"^\s{4}(\S+)\s{2,}(.*)$")


def _test_local(core: Core, workspace_id: str, name: str) -> McpTest:
    """A local server: its container may still be downloading the server the
    first time it starts (a minute or two), so a failed test is tried again
    for up to ~3 minutes before the owner sees an error."""
    deadline = time.monotonic() + 180
    while True:
        result = _test_with_hermes(core, workspace_id, name)
        if result.ok or time.monotonic() > deadline:
            if not result.ok:
                return McpTest(
                    ok=False,
                    error=(
                        f"{result.error} (It runs in this workspace's own container; the "
                        "first start downloads the server and can take a few minutes.)"
                    ),
                )
            return result
        time.sleep(10)


def _test_with_hermes(core: Core, workspace_id: str, name: str, *, has_key: bool = True) -> McpTest:
    """`hermes mcp test <name>` in the workspace's root (hermes_cli/mcp_config.py
    `cmd_mcp_test`): Hermes's own client, with the root's key or sign-in. Walled
    like the root's gateway: a stdio server's command comes from the root's
    config.yaml, which that gateway can write."""
    assert core.engine is not None
    try:
        out = hermes_cli.walled_cli(core.engine, workspace_id, "mcp", "test", name, timeout=90)
    except EngineError as error:
        return McpTest(
            ok=False, error=mcp_errors.readable_mcp_error(str(error), workspace_id, has_key=has_key)
        )
    if "✓ Connected" not in out:
        last = [ln.strip() for ln in out.splitlines() if ln.strip()][-1:] or ["no answer"]
        return McpTest(
            ok=False, error=mcp_errors.readable_mcp_error(last[0], workspace_id, has_key=has_key)
        )
    tools = [
        McpTool(name=m.group(1), description=m.group(2).strip())
        for ln in out.split("Tools discovered", 1)[-1].splitlines()
        if (m := _TOOL_LINE.match(ln))
    ]
    return McpTest(ok=True, tools=tools)
