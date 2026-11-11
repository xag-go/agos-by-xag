"""Create a Telegram bot with a QR code (no BotFather, no token to copy).

Hermes's own "Create with QR": its client of Nous's Telegram setup service
(`hermes_cli/telegram_managed_bot.py`: `create_pairing`, `poll_pairing_result_once`)
does every call, run in Hermes's own runtime. AGOS keeps no client of its own; it
only holds the pairing while the QR is on screen and saves the bot when it's ready.
- AGOS asks Hermes for a pairing → a Telegram link (shown as a QR code).
- The owner opens it on his phone and taps "Create Bot": Telegram creates a bot
  that belongs to him.
- AGOS asks Hermes to poll once per web poll; when ready it receives the bot token
  and the owner's Telegram user id, once.

The token never goes to the web app: it is saved like a pasted one (encrypted,
Settings → Channels), with the owner's id as the only allowed person, and the
bot is linked to the workspace's Co-Founder chat when a workspace asked for it.
Hermes's own override of the service address (`TELEGRAM_ONBOARDING_URL`) applies.
"""

from __future__ import annotations

import json
import logging
import secrets
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from agos_core.config import EngineConfig
from agos_core.engine import hermes_contract
from agos_core.engine.loop_guard import off_loop
from agos_core.engine.models import hermes_python
from agos_core.engine.waits import hermes_wait

log = logging.getLogger("agos.telegram_setup")

PAIRING_TTL = 600  # seconds; the service's own expiry wins when it's shorter
MARKER = "AGOS-TG "

# Runs in Hermes's runtime: one call of Hermes's own client, the answer as JSON.
# The request (with the poll token) comes on stdin, never on the command line.
_CALL = r"""
import dataclasses, json, sys
from hermes_cli import telegram_managed_bot as tmb
req = json.loads(sys.stdin.read())
out = {}
if req["op"] == "start":
    p = tmb.create_pairing(bot_name=req["bot_name"])
    out["pairing"] = dataclasses.asdict(p) if p else None
else:
    try:
        r = tmb.poll_pairing_result_once(None, tmb.TelegramPairing(**req["pairing"]))
    except Exception as error:  # the engine counts these as "not ready yet"
        out["error"] = type(error).__name__
    else:
        out["result"] = dataclasses.asdict(r) if r else None
print("AGOS-TG " + json.dumps(out))
"""


class PairingError(Exception):
    pass


@dataclass
class Pairing:
    id: str  # AGOS's own id (the web never sees the service's ids or poll token)
    hermes: dict[str, Any] = field(repr=False)  # Hermes's TelegramPairing, as it gave it
    link: str
    suggested_username: str
    expires_at: float
    workspace_id: str | None
    bot_name: str
    status: Literal["waiting", "ready", "saved", "error", "expired"] = "waiting"
    error: str = ""
    bot_username: str = ""
    connection_id: int | None = None
    token: str = field(default="", repr=False)
    owner_id: str = ""


_PAIRINGS: dict[str, Pairing] = {}
_LOCK = threading.Lock()


def _hermes(engine: EngineConfig, request: dict[str, Any]) -> dict[str, Any]:
    """One call of Hermes's own Telegram setup client, in Hermes's runtime."""
    from agos_core.engine.hermes import child_env

    env = {
        "HOME": str(engine.host_home),
        "HERMES_HOME": str(engine.hermes_home),
        **engine.runtime_env(),
    }
    try:
        off_loop("hermes telegram setup")
        done = subprocess.run(  # noqa: S603 - Hermes's own Python, fixed argv
            [hermes_python(engine), "-c", _CALL],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=hermes_wait(40),
            env=child_env(env),
            check=False,
            start_new_session=True,
        )
        hermes_contract.ran(done)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        raise PairingError(
            f"The engine's Telegram setup didn't answer ({type(error).__name__})."
        ) from None
    lines = [ln for ln in done.stdout.splitlines() if ln.startswith(MARKER)]
    if done.returncode != 0 or not lines:
        log.info("telegram setup failed (%s): %s", done.returncode, done.stderr[-500:])
        raise PairingError("The engine's Telegram setup failed. Try again in a moment.")
    answer = json.loads(lines[-1][len(MARKER) :])
    return answer if isinstance(answer, dict) else {}


def _prune() -> None:
    now = time.time()
    for key in [k for k, p in _PAIRINGS.items() if p.expires_at + 600 < now]:
        _PAIRINGS.pop(key, None)


def _expiry(value: object) -> float:
    ours = time.time() + PAIRING_TTL
    if not isinstance(value, str) or not value:
        return ours
    try:
        theirs = datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return ours
    return min(ours, theirs)


def start(engine: EngineConfig, bot_name: str, workspace_id: str | None) -> Pairing:
    made = _hermes(engine, {"op": "start", "bot_name": bot_name}).get("pairing")
    if not isinstance(made, dict):
        raise PairingError(
            "The Telegram setup service can't be reached or refused. Try again in a moment."
        )
    link = str(made.get("deep_link") or "")
    if not link.startswith("https://t.me/"):
        raise PairingError("The Telegram setup service sent an incomplete answer.")
    pairing = Pairing(
        id=secrets.token_urlsafe(16),
        hermes=made,
        link=link,
        suggested_username=str(made.get("suggested_username") or ""),
        expires_at=_expiry(made.get("expires_at")),
        workspace_id=workspace_id,
        bot_name=bot_name,
    )
    with _LOCK:
        _prune()
        _PAIRINGS[pairing.id] = pairing
    return pairing


def get(pairing_id: str) -> Pairing | None:
    with _LOCK:
        return _PAIRINGS.get(pairing_id)


def poll(engine: EngineConfig, pairing: Pairing) -> Pairing:
    """Asks the service once (Hermes's client). When the bot is ready, the token is
    kept here (in memory) until the caller saves it. Like Hermes's own setup, a
    failed or unfinished poll means "not ready yet" until the pairing expires."""
    if pairing.status != "waiting":
        return pairing
    if time.time() > pairing.expires_at:
        pairing.status, pairing.error = "expired", "This QR code expired. Make a new one."
        return pairing
    try:
        answer = _hermes(engine, {"op": "poll", "pairing": pairing.hermes})
    except PairingError as error:
        log.info("telegram setup poll: %s", error)
        return pairing
    result = answer.get("result")
    if not isinstance(result, dict):
        return pairing
    owner = result.get("owner_user_id")
    if not isinstance(owner, int) or isinstance(owner, bool) or owner <= 0:
        pairing.status, pairing.error = (
            "error",
            "The Telegram setup service didn't say who you are. Make a new QR code.",
        )
        return pairing
    pairing.token, pairing.owner_id = str(result.get("token") or ""), str(owner)
    pairing.bot_username = str(result.get("bot_username") or "")
    pairing.status = "ready"
    return pairing


def forget_token(pairing: Pairing) -> None:
    pairing.token = ""
    pairing.hermes = {}
