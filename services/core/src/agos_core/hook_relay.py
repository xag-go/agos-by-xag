"""The webhook relay: the only thing a public tunnel may point at.

It listens on 127.0.0.1 and passes on ONE kind of request, `POST /webhooks/<route>`
(body up to 512 KB), to the Hermes of the workspace that owns the route (its
webhook platform, on 127.0.0.1 only; the map is AGOS's `system/hook-routes.json`).
Hermes checks the signature and the rest. Everything else (the web app, the API,
GET requests) gets 404 here, so a tunnel to this port can never reach the rest of
AGOS.

    python -m agos_core.hook_relay            # 127.0.0.1:8767 -> 127.0.0.1:<route's port>
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_BODY = 512 * 1024
PATH = re.compile(r"^/webhooks/(agos-[a-z0-9-]{20,60})$")
# Hermes's own webhook headers, passed on untouched: Hermes checks every signature
# scheme itself (gateway/platforms/webhook.py _validate_signature: Svix, Standard
# Webhooks, Linear, GitHub, GitLab token, generic V2/V1) and reads the event and
# the delivery id from them (_handle_webhook).
HERMES_HEADERS = (
    "content-type",
    "x-hub-signature-256",
    "x-github-event",
    "x-github-delivery",
    "x-gitlab-event",
    "x-gitlab-token",
    "svix-id",
    "svix-timestamp",
    "svix-signature",
    "webhook-id",
    "webhook-timestamp",
    "webhook-signature",
    "linear-signature",
    "x-webhook-signature",
    "x-webhook-signature-v2",
    "x-webhook-timestamp",
    "x-request-id",
)
# AGOS's own names, and older XAG apps' from before the rename (x-xag-*): the only
# headers the relay renames, into Hermes's GitHub-style names.
LEGACY_SIGNATURES = ("x-agos-signature", "x-xag-signature")
LEGACY_EVENTS = ("x-agos-event", "x-xag-event")
LEGACY_DELIVERIES = ("x-agos-delivery", "x-xag-delivery")
PASSED_HEADERS = HERMES_HEADERS + LEGACY_SIGNATURES + LEGACY_EVENTS + LEGACY_DELIVERIES
DATA = os.environ.get("AGOS_DATA_DIR", str(Path("~/agos-data").expanduser()))
# Where Hermes reads a delivery id (its retries are dropped by it).
_DELIVERY_IDS = ("x-github-delivery", "svix-id", "webhook-id", "x-request-id")


def port_of(route: str) -> int | None:
    try:
        found = json.loads((Path(DATA) / "system" / "hook-routes.json").read_text()).get(route)
    except (OSError, ValueError):
        return None
    return int(found) if isinstance(found, int) else None


def hermes_headers(given: dict[str, str]) -> dict[str, str]:
    """What reaches Hermes: its own headers as sent, plus the x-agos-*/x-xag-*
    names renamed GitHub style. Nothing else (no cookie, no AGOS token)."""
    out = {name: given[name] for name in HERMES_HEADERS if given.get(name)}
    out.setdefault("content-type", "application/json")
    legacy = next((given[n] for n in LEGACY_SIGNATURES if given.get(n)), "")
    if legacy and "x-hub-signature-256" not in out:
        # Signed over the body (what AGOS always checked): Hermes reads it GitHub
        # style. A Standard Webhooks signature sent along would make Hermes check
        # that one first, so it stays out.
        value = legacy.split("=", 1)[1] if legacy.lower().startswith("sha256=") else legacy
        out["x-hub-signature-256"] = "sha256=" + value.strip().lower()
        for name in ("webhook-timestamp", "webhook-signature"):
            out.pop(name, None)
    event = next((given[n] for n in LEGACY_EVENTS if given.get(n)), "")
    if event and "x-github-event" not in out and "x-gitlab-event" not in out:
        out["x-github-event"] = event  # the route's filters see it as "event"
    delivery = next((given[n] for n in LEGACY_DELIVERIES if given.get(n)), "")
    if delivery and not any(n in out for n in _DELIVERY_IDS):
        out["x-request-id"] = delivery[:200]
    return out


class Relay(BaseHTTPRequestHandler):
    server_version = "agos-hooks"
    sys_version = ""

    def _answer(self, status: int, body: bytes = b'{"status":"not found"}') -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._answer(200, b'{"ok":true}')
            return
        self._answer(404)

    do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = do_GET

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        match = PATH.match(path)
        port = port_of(match.group(1)) if match else None
        if port is None:
            self._answer(404)
            return
        try:
            size = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            size = -1
        if size < 0 or size > MAX_BODY:
            self._answer(413, b'{"status":"too big"}')
            return
        body = self.rfile.read(size) if size else b""
        given = {k.lower(): v for k in PASSED_HEADERS if (v := self.headers.get(k))}
        names = " ".join(sorted({k.lower() for k in self.headers}))
        print(f"hook headers: {names}", flush=True)  # names only, never values
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=body,
            headers=hermes_headers(given),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as reply:  # noqa: S310
                self._answer(reply.status, reply.read()[:2000])
        except urllib.error.HTTPError as error:
            self._answer(error.code, error.read()[:2000])
        except OSError:
            self._answer(503, b'{"status":"the workspace is not running"}')

    def log_message(self, format: str, *args: object) -> None:
        # Never log the path: it carries the secret token.
        print(f"hook {self.command} -> {args[1] if len(args) > 1 else ''}", flush=True)


def main() -> None:
    port = int(os.environ.get("AGOS_HOOKS_PORT", "8767"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Relay)
    print(f"webhook relay on 127.0.0.1:{port} -> the workspaces' Hermes", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
