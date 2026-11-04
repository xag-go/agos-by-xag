"""Read vs act, inside Hermes: which tool calls read untrusted content (taint.py marks
their session).

- the web: `web_search`, `web_extract`, `web_crawl`, `x_search`, every `browser_*`
  tool, `computer_use` (a desktop shows whatever is on it), a `vision_analyze` of an
  http(s) image, a `video_analyze` of a URL;
- an app or MCP server's answer (`mcp_<server>_*`: email, Slack, GitHub...), unless
  the owner put that app on the workspace's trusted list (Settings → Autonomy →
  Trusted apps; the policy file's `trustedApps`, default empty: every app is outside);
- earlier conversations (`session_search` / `chat_history_lookup`): they may hold
  what an earlier untrusted read brought in;
- a terminal / execute_code command that fetches from outside, with or without a URL
  in it: curl, wget, an http(s) URL, the mail / issue / git CLIs that read other
  people's words (gws, himalaya, gh, git pull / fetch / clone, ssh, nc), a Python or
  Node one-liner using urllib / requests / httpx / fetch / socket;
- a file from a folder outside the workspace (`/shared`), however the path is
  written (relative to /workspace, `..`, `cat`, `grep`, `head`...).
"""

from __future__ import annotations

import posixpath
import re
import shlex
from typing import Any

_WEB = {"web_search", "web_extract", "web_crawl", "x_search"}
_HISTORY = {"session_search", "chat_history_lookup"}
# A command that brings in outside words (a word of its own, not part of another).
_FETCH = re.compile(
    r"(?<![\w.-])(curl|wget|aria2c|lynx|w3m|gws|himalaya|gh|ssh|scp|rsync|nc|ncat|telnet"
    r"|ftp|sftp|mutt|neomutt|fetchmail|mbsync|offlineimap|yt-dlp)(?![\w.-])"
    r"|https?://|ftp://|\bgit\s+(pull|fetch|clone|remote\s+update)\b"
    r"|\b(urllib|requests|httpx|aiohttp|http\.client|socket|imaplib|poplib|smtplib"
    r"|websocket|ftplib|paramiko)\b|\bfetch\s*\(|\bnew\s+WebSocket\b|\bXMLHttpRequest\b",
    re.IGNORECASE,
)
SANDBOX_CWD = "/workspace"
SHARED = "/shared"


def outside_path(path: str, cwd: str = SANDBOX_CWD) -> bool:
    """A path in the shared folder outside the workspace, however it is written."""
    if not path:
        return False
    where = posixpath.normpath(posixpath.join(cwd, path.strip()))
    return where == SHARED or where.startswith(SHARED + "/")


def _shared_in(text: str) -> bool:
    """A command naming a file of /shared (cat /shared/x, ../shared/x, cd /shared)."""
    if "shared" not in text:
        return False
    try:
        words = shlex.split(text, posix=True)
    except ValueError:
        words = text.split()
    for word in words:
        for part in re.split(r"[=:;|&<>()]", word):
            if "shared" in part and outside_path(part):
                return True
    return False


def trusted_app(name: str, trusted: list[str]) -> bool:
    """`mcp_<server>_<tool>` of a server the owner trusts."""
    return any(t and (name == f"mcp_{t}" or name.startswith(f"mcp_{t}_")) for t in trusted)


def source_of(tool: str, args: dict[str, Any], trusted: list[str] | None = None) -> str:
    """What untrusted content this call reads ("" = nothing from outside)."""
    name = tool.lower()
    if name in _WEB:
        return f"the web ({name})"
    if name.startswith("browser_"):
        return "a web page (the browser)"
    if name == "computer_use":
        return "a screen of the agent's desktop (computer_use)"
    if name.startswith("mcp_"):
        cleaned = [str(t).lower() for t in trusted or []]
        return "" if trusted_app(name, cleaned) else f"an app or MCP server's answer ({name[:60]})"
    if name in _HISTORY:
        return f"an earlier conversation ({name})"
    if name == "vision_analyze" and str(args.get("image_url") or "").startswith("http"):
        return "an image from the web"
    if name == "video_analyze" and "://" in str(args.get("video_url") or ""):
        return "a video from the web"
    if name in ("terminal", "execute_code"):
        text = str(args.get("command") or args.get("code") or "")
        if _FETCH.search(text):
            return "something fetched from outside (a command)"
        if _shared_in(text):
            return "a file from a folder outside the workspace"
    if name in ("read_file", "search_files") and outside_path(str(args.get("path") or "")):
        return "a file from a folder outside the workspace"
    return ""
