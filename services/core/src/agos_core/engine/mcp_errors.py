"""An MCP server's refusal in the owner's words (pure; moved out of
actions/library.py, which runs the test)."""

from __future__ import annotations

import re

_NEEDS_KEY = re.compile(r"sign in|agent key|unauthori[sz]ed|\b401\b|-32001|forbidden|\b403\b", re.I)


def readable_mcp_error(text: str, workspace_id: str | None, *, has_key: bool) -> str:
    """Hermes's raw exception text -> what the owner should do."""
    inner = re.search(r"MCPError\(-?\d+, '([^']*)'", text)
    message = inner.group(1) if inner else text
    if _NEEDS_KEY.search(text):
        if not workspace_id:
            return (
                f"No workspace is signed in to this server yet ({message}). Sign in per "
                "workspace (OAuth), or paste a key in the workspace → Settings → Capabilities "
                "→ this server → Configure."
            )
        if not has_key:
            return (
                f"The server wants a key ({message}). Paste it in “Key for this workspace” "
                "above and save, then try again."
            )
        return (
            f"The server refused this key ({message}). Check the key is right, not expired, "
            "and has the scopes this server needs."
        )
    return message
