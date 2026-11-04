# mypy: ignore-errors
"""Runs ONE connector login with Hermes's own MCP OAuth code, then exits.

agos-core starts it with the Python that runs Hermes and HERMES_HOME = the
workspace's login profile (a profile of the AGOS Hermes, so Hermes finds its own
install), whose `mcp-tokens` is a link to that workspace's login folder: the
tokens land in `<workspace login folder>/mcp-tokens/<name>.json`, never in the
owner's ~/.hermes and never in another workspace's folder.
Hermes does discovery, client registration, PKCE, state checks, token exchange
and refresh; AGOS only carries the two browser steps through its web app.

Protocol (one JSON object per line):
  argv[1]  = JSON {"name", "url", "redirect_uri"}
  stdout  -> {"event": "authorize", "url": ...}     the page to open
  stdin   <- {"code", "state", "error", "iss"}      the redirect back to AGOS
  stdout  -> {"event": "done", "tools": [...]} or {"event": "error", "message"}

Not imported by agos-core (Hermes isn't importable there); it is only run.
"""

import asyncio
import json
import os
import sys
import threading
from pathlib import Path

LOGIN_TIMEOUT_S = 600


def say(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def main() -> int:
    job = json.loads(sys.argv[1])
    name, url, redirect_uri = job["name"], job["url"], job["redirect_uri"]
    home = os.environ.get("HERMES_HOME", "")
    root = (Path.home() / ".hermes").resolve()
    resolved = Path(home).resolve() if home else root
    # Only an AGOS login profile, whose tokens folder is a workspace's login folder.
    if resolved == root or not (Path(home) / "mcp-tokens").is_symlink():
        say({"event": "error", "message": "refusing: not AGOS's login profile"})
        return 2
    sys.path.insert(0, str(Path.cwd()))

    from hermes_cli.mcp_config import _oauth_tokens_present, _probe_single_server
    from tools.mcp_dashboard_oauth import DashboardOAuthFlow, dashboard_oauth_flow
    from tools.mcp_oauth import force_interactive_oauth

    flow = DashboardOAuthFlow(
        flow_id=os.urandom(8).hex(),
        server_name=name,
        profile=None,
        hermes_home=home,
        redirect_uri=redirect_uri,
    )

    async def publish(url: str) -> None:  # Hermes's own parameter name
        await original_publish(url)
        say({"event": "authorize", "url": url})

    original_publish = flow.publish_authorization_url
    flow.publish_authorization_url = publish  # type: ignore[method-assign]

    def read_callback() -> None:
        line = sys.stdin.readline()
        if not line:
            flow.mark_error("login cancelled", cancelled=True)
            return
        try:
            data = json.loads(line)
            flow.deliver_callback(
                code=data.get("code"),
                state=data.get("state"),
                error=data.get("error"),
                iss=data.get("iss"),
            )
        except (ValueError, TypeError) as error:
            flow.mark_error(f"bad callback: {error}")

    threading.Thread(target=read_callback, daemon=True).start()
    config: dict[str, object] = {"url": url, "auth": "oauth", "connect_timeout": LOGIN_TIMEOUT_S}
    if isinstance(job.get("oauth"), dict):
        config["oauth"] = job["oauth"]  # the owner's own client (Google's servers)
    try:
        with force_interactive_oauth(), dashboard_oauth_flow(flow):
            tools = _probe_single_server(name, config, connect_timeout=LOGIN_TIMEOUT_S)
        if not _oauth_tokens_present(name):
            raise RuntimeError("the app answered but gave no login token")
    except Exception as error:  # noqa: BLE001 - reported to AGOS, never raised
        message = str(error) or type(error).__name__
        say({"event": "error", "message": message[:500]})
        return 1
    say({"event": "done", "tools": [{"name": t, "description": d[:300]} for t, d in tools]})
    return 0


if __name__ == "__main__":
    asyncio.set_event_loop_policy(None)
    raise SystemExit(main())
