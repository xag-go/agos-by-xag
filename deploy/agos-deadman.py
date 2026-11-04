#!/usr/bin/env python3
"""AGOS dead-man: tells the owner on Telegram when the core is down (no core needed).

Run every minute by agos-deadman.timer (deploy/install-server.sh), as the AGOS
user. Standard library only. Each run:

1. GET the core's /health (AGOS_HEALTH_URL, default http://127.0.0.1:8766/health).
2. Down: the first failure's time is kept in the state file. Once it has been
   down for AGOS_DEADMAN_AFTER seconds (default 180) one message goes to the
   owner, straight to Telegram's Bot API, and no more until it is back.
3. Up again after a message: one "back" message; the state is cleared.

Where to send: <data>/system/deadman.json, written by the core while it runs
(actions/deadman.py): the Hermes .env holding the workspace's bot token
(TELEGRAM_BOT_TOKEN, read only when sending) and the owner's chat id. No such
file (no bot yet): the message only goes to the journal (stdout).

Environment: AGOS_DATA_DIR (required unless the two paths below are given),
AGOS_DEADMAN_PLACE, AGOS_DEADMAN_STATE, AGOS_HEALTH_URL, AGOS_DEADMAN_AFTER,
AGOS_TELEGRAM_API (default https://api.telegram.org; tests point it at a fake).
Exit code 0 always (a failed alert is printed, the timer runs again).
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=10) as answer:  # noqa: S310 - local URL
            return bool(answer.status == 200 and json.loads(answer.read() or b"{}").get("ok"))
    except (OSError, ValueError, urllib.error.URLError, socket.timeout):
        return False


def token_from(env_file: Path) -> str:
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            return line.split("=", 1)[1].strip().strip("'\"")
    return ""


def send(place_file: Path, api: str, text: str) -> str:
    """Sends `text` to the owner; returns what happened (for the journal)."""
    try:
        place = json.loads(place_file.read_text(encoding="utf-8"))
        token = token_from(Path(place["envFile"]))
        chat = str(place["chatId"])
    except (OSError, ValueError, KeyError, TypeError):
        return "no Telegram place (no bot set up yet): journal only"
    if not token or not chat:
        return "no bot token or owner chat: journal only"
    body = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    url = f"{api.rstrip('/')}/bot{token}/sendMessage"
    try:
        with urllib.request.urlopen(url, data=body, timeout=15) as answer:  # noqa: S310
            return f"sent to Telegram ({answer.status})"
    except (OSError, urllib.error.URLError) as error:
        return f"Telegram refused or unreachable: {type(error).__name__}"


def main() -> int:
    data = _env("AGOS_DATA_DIR")
    system = Path(data) / "system" if data else None
    place_env = _env("AGOS_DEADMAN_PLACE")
    state_env = _env("AGOS_DEADMAN_STATE")
    if system is None and not (place_env and state_env):
        print("AGOS_DATA_DIR is not set", file=sys.stderr)
        return 0
    place = Path(place_env) if place_env else system / "deadman.json"  # type: ignore[operator]
    state_file = Path(state_env) if state_env else system / "deadman.state"  # type: ignore[operator]
    url = _env("AGOS_HEALTH_URL", "http://127.0.0.1:8766/health")
    after = float(_env("AGOS_DEADMAN_AFTER", "180"))
    api = _env("AGOS_TELEGRAM_API", "https://api.telegram.org")
    host = socket.gethostname()
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    moment = time.time()
    if healthy(url):
        if state.get("told"):
            print(send(place, api, f"✅ AGOS is back up on {host}."))
        if state:
            state_file.unlink(missing_ok=True)
        return 0
    since = float(state.get("since") or moment)
    down = moment - since
    told = bool(state.get("told"))
    if not told and down >= after:
        minutes = max(1, round(down / 60))
        what = send(
            place,
            api,
            f"🔴 AGOS is down on {host}: its core hasn't answered for {minutes} min. "
            "Telegram chats with your agents may still work; AGOS's cards and "
            "automations wait. On the server: agos status, then agos restart.",
        )
        print(f"core down {int(down)} s: {what}")
        told = True
    else:
        print(f"core down {int(down)} s")
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"since": since, "told": told}), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
