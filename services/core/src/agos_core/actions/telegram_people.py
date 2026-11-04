"""Who may write to a workspace's bot: Hermes's own allowlist and DM pairing.

AGOS keeps no list of its own. Hermes's gateway lets a Telegram user in when he is
in the root's `TELEGRAM_ALLOWED_USERS` (.env) or approved in its pairing store
(gateway/authz_mixin.py `_principal_authorized`: the pairing store and the
allowlist, as a union). Someone new who writes to the bot in a private chat gets
Hermes's pairing code (`unauthorized_dm_behavior: pair`, global and Telegram's own:
AGOS's profile settings);
his request shows in AGOS and the owner approves it there
(`hermes pairing approve telegram <request id>`), or removes someone
(`hermes pairing revoke telegram <user id>`). Approving also writes him into
`TELEGRAM_ALLOWED_USERS` once that list exists (gateway/pairing.py
`_sync_allowlist_add`).

AGOS reads Hermes's files (the root's .env, `platforms/pairing/telegram-*.json`)
and changes them only through Hermes's CLI.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.db.records import Record
from agos_core.hermes_gateway import cli as hermes_cli

PLATFORM = "telegram"
ENV = "TELEGRAM_ALLOWED_USERS"
CODE_TTL_S = 3600  # Hermes's pairing request lives an hour (gateway/pairing.py)


class Person(Record):
    id: str
    name: str = ""


class PairingRequest(Record):
    request_id: str
    id: str
    name: str = ""
    age_minutes: int = 0


def _home(core: Core, workspace_id: str) -> Path | None:
    if core.engine is None:
        return None
    home = core.engine.profile_home(workspace_id)
    return home if home.is_dir() else None


def _pairing_dir(home: Path) -> Path:
    """Hermes's pairing folder (hermes_constants.get_hermes_dir: a legacy `pairing/`
    with files in it wins over `platforms/pairing/`)."""
    old = home / "pairing"
    if old.is_dir() and any(old.iterdir()):
        return old
    return home / "platforms" / "pairing"


def _load(path: Path) -> dict[str, Any]:
    try:
        found = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def env_ids(core: Core, workspace_id: str) -> list[str]:
    home = _home(core, workspace_id)
    if home is None:
        return []
    from agos_core.engine import config_file

    raw = config_file.read_env(home).get(ENV, "").strip().strip("\"'")
    return [x.strip() for x in raw.split(",") if x.strip()]


def _approved(home: Path) -> dict[str, Any]:
    return _load(_pairing_dir(home) / f"{PLATFORM}-approved.json")


def people(core: Core, workspace_id: str) -> list[Person]:
    """Everyone the bot listens to: Hermes's allowlist, then those approved by pairing."""
    home = _home(core, workspace_id)
    if home is None:
        return []
    approved = _approved(home)
    out: list[Person] = []
    for uid in [*env_ids(core, workspace_id), *approved]:
        if uid == "*" or any(p.id == uid for p in out):
            continue
        info = approved.get(uid)
        name = str(info.get("user_name") or "") if isinstance(info, dict) else ""
        out.append(Person(id=str(uid), name=name))
    return out


def ids(core: Core, workspace_id: str) -> list[str]:
    return [p.id for p in people(core, workspace_id)]


def lets_in(core: Core, workspace_id: str, user_id: str) -> bool:
    """Hermes's own answer for a Telegram sender: in the root's allowlist (`*` =
    everyone) or approved by its pairing, asked of Hermes's public
    PairingStore.is_approved in the root (the union its gateway checks,
    gateway/authz_mixin.py `_principal_authorized`). Used for the /commands AGOS
    mirrors: Hermes fires no hook after its own check for a slash command
    (gateway/run_inbound.py: `_hm_dispatch_idle_commands` returns before
    `post_gateway_admission`), and its check itself is private. Hermes not
    answering lets nobody new in."""
    from agos_core.engine.hermes import EngineError

    user_id = str(user_id or "").strip()
    home = _home(core, workspace_id)
    if not user_id or home is None or core.engine is None:
        return False
    allowed = env_ids(core, workspace_id)
    if "*" in allowed or user_id in allowed:
        return True
    try:
        return core.engine.pairing_approved(home, PLATFORM, user_id)
    except (EngineError, OSError, ValueError):
        return False


def owner_id(core: Core, workspace_id: str) -> str:
    """The first person the bot listens to (its private chat is the Co-Founder's)."""
    return next((i for i in ids(core, workspace_id) if i.isdigit()), "")


def pending(core: Core, workspace_id: str) -> list[PairingRequest]:
    """People who wrote to the bot and wait for the owner's yes (Hermes's pending
    pairing requests; the code itself is never stored, only its hash)."""
    home = _home(core, workspace_id)
    if home is None:
        return []
    out: list[PairingRequest] = []
    at = time.time()
    for request_id, info in _load(_pairing_dir(home) / f"{PLATFORM}-pending.json").items():
        if not isinstance(info, dict) or not isinstance(info.get("hash"), str):
            continue
        created = info.get("created_at")
        if not isinstance(created, int | float) or at - created > CODE_TTL_S:
            continue
        out.append(
            PairingRequest(
                request_id=str(request_id),
                id=str(info.get("user_id") or ""),
                name=str(info.get("user_name") or ""),
                age_minutes=int((at - created) / 60),
            )
        )
    return out


def allow(core: Core, workspace_id: str, user_ids: list[str]) -> None:
    """People the bot starts with (its setup): into Hermes's allowlist."""
    wanted = [u for u in user_ids if u and u not in env_ids(core, workspace_id)]
    if not wanted or core.engine is None:
        return
    value = ",".join([*env_ids(core, workspace_id), *wanted])
    hermes_cli.cli(core.engine, workspace_id, "config", "set", ENV, value)


def approve(core: Core, workspace_id: str, request_id: str) -> str:
    """The owner's yes to a pairing request: Hermes's own approval. Returns who."""
    found = next((r for r in pending(core, workspace_id) if r.request_id == request_id), None)
    if found is None or core.engine is None:
        raise ActionError("This request is gone (it lasts an hour). Ask them to write again.")
    hermes_cli.cli(core.engine, workspace_id, "pairing", "approve", PLATFORM, request_id)
    if found.id not in ids(core, workspace_id):
        raise ActionError("Hermes didn't take the approval. Try again.", 503)
    return found.id


def remove(core: Core, workspace_id: str, user_id: str) -> None:
    """The bot stops listening to him: out of Hermes's pairing store and allowlist."""
    if core.engine is None or user_id not in ids(core, workspace_id):
        return
    home = _home(core, workspace_id)
    if home is not None and user_id in _approved(home):
        hermes_cli.cli(core.engine, workspace_id, "pairing", "revoke", PLATFORM, user_id)
    rest = [u for u in env_ids(core, workspace_id) if u != user_id]
    if rest != env_ids(core, workspace_id):
        hermes_cli.cli(core.engine, workspace_id, "config", "set", ENV, ",".join(rest))
    if user_id in ids(core, workspace_id):
        raise ActionError("Hermes didn't take it. Try again.", 503)
