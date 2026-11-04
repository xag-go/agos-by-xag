"""Model and effort picks told in a Hermes conversation: Hermes's own /model for the
chat's pick, the old per-chat model notes moved once, and the answer to AGOS's
own /model.

Owns: the hermes.effort.* / model notes kept per conversation, and the chat's model
read back from them and Hermes's own pick (chat_model, out of db/chats.py).
Must not: send other commands or mirror messages.

Part of the Channel service (moved out of actions/hermes_channel.py, which re-exports
every name for old callers)."""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Any

from agos_core.actions.services.channel import hermes_addresses
from agos_core.context import Core
from agos_core.db import app_settings, hermes_inbox
from agos_core.db import chats as repo
from agos_core.db import hermes_chats as hc
from agos_core.db.rows import load_json
from agos_core.db.workspaces import model_of
from agos_core.domain.models import ModelSelection
from agos_core.engine import doorbell
from agos_core.engine.models import selection_from_hermes

__all__ = [
    "EFFORT_KEY",
    "MOVE_KEY",
    "OLD_MODEL_KEY",
    "chat_model",
    "effort_note",
    "model_command",
    "move_old_models",
    "tell_model",
]


def tell_model(
    core: Core, workspace_id: str, chat_id: int, model: Any, *, force: bool = False
) -> bool:
    """The chat's model as Hermes's own /model for this conversation (`--session`):
    the one asked (`model`), else the one it shows. Sent when this run of its
    gateway wasn't told it yet (Hermes forgets the reasoning effort on a restart)."""
    where = hermes_addresses.chat_on_hermes(core, chat_id)
    row = repo.any_row(core.db, chat_id)
    if where is None or row is None or where["connection_id"] is not None:
        return False
    address = str(where["address"])
    if model is None:
        # A chat that follows the workspace's model needs no /model (Hermes runs its
        # profile's own); one with its own pick is told again after a restart.
        store = hc.store()
        place = repo.where_of(core.db, row)
        own = store is not None and place is not None and store.model_override(place) is not None
        if not own:
            return False
    wanted = model if model is not None else chat_model(core.db, row)
    if force:
        app_settings.delete_setting(core.db, EFFORT_KEY + address)
    switch = model_command(
        core,
        address,
        wanted.model_dump() if hasattr(wanted, "model_dump") else wanted,
        workspace_id,
    )
    if not switch:
        return False
    hermes_inbox.put(core.db, workspace_id, address, switch, "command")
    doorbell.ring(doorbell.INBOX, workspace_id)
    return True


EFFORT_KEY = "hermes.effort."
# A conversation's model is Hermes's own: its /model --session keeps model, provider
# and base_url across restarts (H: gateway/session.py:467 PERSISTABLE_MODEL_OVERRIDE_KEYS,
# read back from its routing table, db/hermes_chats.py `model_override`). Its reasoning
# effort lives only in the running gateway's memory (H: gateway/session_state.py:229
# conversation.reasoning_override, set by gateway/run_config_loaders.py:191
# `_set_session_reasoning_override`), so a restarted gateway forgets it. AGOS keeps only
# that, per conversation: {"model": the Hermes model it goes with, "effort", "told":
# mark of the /model this run of the gateway was sent, "sent": mark of the command}.


def _mark(command: str, gateway: str) -> str:
    return hashlib.sha256(f"{command}@{gateway}".encode()).hexdigest()[:16]


OLD_MODEL_KEY = "hermes.model."  # before: the whole /model told, kept per conversation
MOVE_KEY = "chats.model.move."  # before: chats.model, his pick (migration 103 put it here)


def move_old_models(core: Core) -> int:
    """Once, at core start: AGOS's old copies of a chat's model go. The /model told
    to a gateway becomes the effort note (same marks: nothing is sent again); a pick
    kept in chats.model goes to Hermes as its own /model for the conversation when
    Hermes has none (or has that model but AGOS lost the effort). Hermes's own
    choice wins otherwise. Returns how many picks were told to Hermes."""
    from agos_core.db.app_settings import set_setting
    from agos_core.domain.models import ModelSelection
    from agos_core.engine.models import hermes_model

    for key, value in app_settings.with_prefix(core.db, OLD_MODEL_KEY):
        address = key[len(OLD_MODEL_KEY) :]
        command, _, gateway = str(load_json(value) or "").rpartition("@")
        words = command.split()
        if words[:1] == ["/model"] and len(words) > 1 and not effort_note(core.db, address):
            at = words.index("--reasoning") + 1 if "--reasoning" in words else len(words)
            note = {
                "model": words[1],
                "effort": words[at] if at < len(words) else "",
                "told": _mark(command, gateway),
                "sent": _mark(command, ""),
            }
            set_setting(core.db, EFFORT_KEY + address, note)
        app_settings.delete_setting(core.db, OLD_MODEL_KEY + address)
    told = 0
    store = hc.store()
    for key, value in app_settings.with_prefix(core.db, MOVE_KEY):
        moved = key[len(MOVE_KEY) :]
        try:
            chat_id = int(moved)
            pick = ModelSelection.model_validate(load_json(value))
        except ValueError:
            app_settings.delete_setting(core.db, MOVE_KEY + moved)
            continue
        row = repo.visible_row(core.db, chat_id)
        where = hermes_addresses.chat_on_hermes(core, chat_id) if row is not None else None
        if row is not None and where is not None and where["connection_id"] is None:
            # Only a conversation on AGOS's own platform ever took a /model of his.
            place = repo.where_of(core.db, row)
            override = store.model_override(place) if store and place else None
            wanted = str(hermes_model(pick).get("model") or "")
            note = effort_note(core.db, f"{hermes_addresses.AGOS_PREFIX}{chat_id}")
            lost = override is not None and override.get("model") == wanted and not note
            if repo.pending_command(core.db, row, "/model") is None and (override is None or lost):
                ws = str(row["workspace_id"])
                told += int(tell_model(core, ws, chat_id, pick, force=True))
        app_settings.delete_setting(core.db, MOVE_KEY + moved)
    return told


def effort_note(db: Any, address: str) -> dict[str, str]:
    from agos_core.db.app_settings import get_setting

    note = get_setting(db, EFFORT_KEY + address, {})
    return {str(k): str(v) for k, v in note.items()} if isinstance(note, dict) else {}


def _gateway_mark(core: Core, workspace_id: str | None, address: str) -> str:
    """Which run of the gateway serving this conversation (its pid file): Hermes
    keeps a conversation's model and provider across a restart, not its reasoning
    effort, so a restarted gateway is told the model again."""
    if core.engine is None or workspace_id is None:
        return ""
    member = hermes_addresses.owner_member(core, workspace_id, address)
    if member:
        from agos_core.actions import agent_profiles

        home = core.engine.profile_home(agent_profiles.key(workspace_id, member))
    else:
        home = core.engine.profile_home(workspace_id)
    try:
        return (home / "gateway.pid").read_text().strip()[:64]
    except OSError:
        return ""


def model_command(
    core: Core, address: str, model: Any, workspace_id: str | None = None
) -> str | None:
    """Hermes's own /model for this conversation when the model AGOS shows for it
    (the chat's own pick, else the workspace's) isn't the one this run of its
    gateway was told; None when it is."""
    from agos_core.db.app_settings import set_setting
    from agos_core.domain.models import ModelSelection
    from agos_core.engine.models import hermes_model

    try:
        selection = ModelSelection.model_validate(model)
    except ValueError:
        return None
    wanted = hermes_model(selection)
    if not wanted.get("model") or not wanted.get("provider"):
        return None
    command = f"/model {wanted['model']} --provider {wanted['provider']} --session"
    effort = (wanted.get("model_options") or {}).get("reasoning_effort")
    if effort:
        command += f" --reasoning {effort}"
    told = _mark(command, _gateway_mark(core, workspace_id, address))
    if effort_note(core.db, address).get("told") == told:
        return None
    note = {"model": str(wanted["model"]), "effort": str(effort or ""), "told": told}
    set_setting(core.db, EFFORT_KEY + address, note | {"sent": _mark(command, "")})
    return command


def _own_model_switch(core: Core, workspace_id: str, address: str, text: str) -> bool:
    """Hermes's answer to the /model AGOS sent by itself for this conversation."""
    if not text.startswith("Model switched to"):
        return False
    sent = hermes_inbox.last_command(core.db, workspace_id, address)
    sent_mark = effort_note(core.db, address).get("sent")
    return sent is not None and sent_mark == _mark(sent, "")


def chat_model(db: sqlite3.Connection, row: sqlite3.Row, *, kept: bool = False) -> ModelSelection:
    """The chat's model: Hermes's own pick for its conversation (/model --session),
    else the workspace's (Hermes's config). The reasoning effort is the one AGOS told
    with it: Hermes doesn't keep it across a restart (gateway/session.py
    PERSISTABLE_MODEL_OVERRIDE_KEYS), actions/hermes_channel.py EFFORT_KEY.
    `kept`: a list's (Hermes's pick kept while its store is unchanged)."""
    pending = repo.pending_command(db, row, "/model")
    if pending:
        found = _selection_of(pending.split())
        if found is not None:
            return found
    store = hc.store()
    where = repo.where_of(db, row)
    if store is not None and where is not None:
        override = store.model_override(where, kept=kept)
        if override:
            found = _from_override(db, row, override)
            if found is not None:
                return found
    return model_of(str(row["workspace_id"]))


def _selection_of(words: list[str]) -> ModelSelection | None:
    """`/model <model> --provider <p> [--reasoning <e>]` → the selection it picks."""
    if not words:
        return None
    return selection_from_hermes(_flag(words, "--provider"), words[0], _effort(words))


def _flag(words: list[str], name: str) -> str:
    at = words.index(name) + 1 if name in words else len(words)
    return words[at] if at < len(words) else ""


def _effort(words: list[str]) -> str:
    """The effort a /model sets (none said: Hermes's standard one)."""
    return _flag(words, "--reasoning") or "standard"


def _from_override(
    db: sqlite3.Connection, row: sqlite3.Row, override: dict[str, str]
) -> ModelSelection | None:
    note = effort_note(db, f"{repo.AGOS_PREFIX}{row['id']}")
    model = str(override.get("model") or "")
    effort = (note.get("effort") or "standard") if note.get("model") == model else "standard"
    return selection_from_hermes(str(override.get("provider") or ""), model, effort)
