#!/usr/bin/env python3
"""A fake `tailscale` command for tests and throwaway rigs: never the real one.

Its state is a JSON file named by FAKE_TAILSCALE_STATE (every key optional):
  daemon    false: the service isn't running
  operator  false: `up` and `serve` are refused (no `--operator` set)
  logged_in true: `status` says Running with the machine and user below
  https     false: `serve` waits for HTTPS to be turned on (prints its link)
  dns_name, login: the machine's tailnet name and the logged-in account
  serving   what `serve --bg <port>` set (written by this script)
Every call is appended to <state>.calls, one JSON list per line.
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

STATE = Path(os.environ["FAKE_TAILSCALE_STATE"])
LOGIN_URL = "https://login.tailscale.com/a/fake123"
HTTPS_URL = "https://login.tailscale.com/f/serve?node=fake"
DENIED = (
    "Access denied: checkprefs access denied\n\nUse 'sudo tailscale up'.\n"
    "To not require root, use 'sudo tailscale set --operator=$USER' once.\n"
)


def state() -> dict[str, Any]:
    try:
        data: dict[str, Any] = json.loads(STATE.read_text())
        return data
    except (OSError, ValueError):
        return {}


def save(data: dict[str, Any]) -> None:
    STATE.write_text(json.dumps(data))


def main(args: list[str]) -> int:
    with STATE.with_name(STATE.name + ".calls").open("a") as calls:
        calls.write(json.dumps(args) + "\n")
    s = state()
    if not s.get("daemon", True):
        print("failed to connect to local tailscaled; it doesn't appear to be running")
        return 1
    if args[:2] == ["status", "--json"]:
        dns = s.get("dns_name", "agos-box.tail1234.ts.net")
        running = bool(s.get("logged_in"))
        print(
            json.dumps(
                {
                    "BackendState": "Running" if running else "NeedsLogin",
                    "AuthURL": "" if running else s.get("auth_url", ""),
                    "Self": {"DNSName": dns + "." if running else "", "UserID": 42},
                    "User": {"42": {"LoginName": s.get("login", "Owner@Example.com")}}
                    if running
                    else None,
                }
            )
        )
        return 0
    if args[:1] == ["up"]:
        if not s.get("operator", True):
            print(DENIED, end="")
            return 1
        if s.get("logged_in"):
            return 0
        print(f"\nTo authenticate, visit:\n\n\t{LOGIN_URL}\n", flush=True)
        for _ in range(600):  # waits for the "login" (a test flips logged_in)
            if state().get("logged_in"):
                print("Success.")
                return 0
            time.sleep(0.1)
        return 1
    if args[:3] == ["serve", "status", "--json"]:
        print(json.dumps(s.get("serve_status", {})))
        return 0
    if args[:2] == ["serve", "--bg"]:
        if not s.get("operator", True):
            print(DENIED, end="")
            return 1
        if not s.get("https", True):
            print(f"Serve is not enabled on your tailnet.\nTo enable, visit:\n\n  {HTTPS_URL}\n")
            sys.stdout.flush()
            time.sleep(60)
            return 1
        s["serving"] = args[2]
        save(s)
        print(f"Available within your tailnet:\n\nhttps://{s.get('dns_name', 'x')}/")
        return 0
    if args[:3] == ["serve", "--https=443", "off"]:
        if "serving" not in s:
            print("error: failed to remove web serve: handler does not exist")
            return 1
        s.pop("serving")
        save(s)
        return 0
    print(f"fake tailscale: unknown command {args}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
